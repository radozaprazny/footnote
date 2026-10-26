#!/usr/bin/env bash
# Create what is missing and deploy the committed app to Azure Container Apps (M6 item 3): Log
# Analytics workspace, registry, image (build and push), environment, app, AcrPull and Foundry
# User for the app's system identity, then a revision from deploy/containerapp.yaml named after
# the commit. Each step looks before it creates, so a second run of the same commit changes
# nothing and a new commit only adds its image and revision. Prints the public URL.
# The image is built from the commit (`git archive`), not from the working tree: its tag and the
# revision suffix are the commit's short sha. The template is the working tree's (a note says
# when it differs from the commit's).
# Usage: scripts/deploy.sh  (needs `az login` with Owner on the resource group, and docker)
set -euo pipefail
cd "$(dirname "$0")/.."

rg=rg-matchlens
location=swedencentral
tags=(project=matchlens owner=radoz expires=2026-11-30)
log=log-matchlens
acr=acrmatchlens
env=cae-matchlens
app=ca-matchlens
foundry=aif-matchlens
foundry_user=53ca6127-db72-4b80-b1b0-d745d6d5456d # "Foundry User": calls a deployment
ready_limit_s=600 # a revision's start and warm-up: 30 s on ACA, 190-211 s at 0.25 vCPU locally

# Rules 4.8 and 5 (the hackathon's Official Rules): from the submission's close to the judging's
# end the app stays up and substantively the same: no re-deploy then, not even a bug fix (owner,
# 24 Oct), unless the Sponsor permits a change
freeze_from=1793170740 # 28 Oct 2026 07:59 CET: the submission closes (27 Oct 23:59 PDT)
freeze_to=1794383940   # 11 Nov 2026 08:59 CET: judging ends (10 Nov 23:59 PST)
now=$(date +%s)
if [ "$now" -ge "$freeze_from" ] && [ "$now" -lt "$freeze_to" ] &&
  [ "${DEPLOY_DURING_JUDGING:-}" != yes ]; then
  echo "deploy.sh: the submission is frozen until 11 Nov 2026 08:59 CET (docs/deploy.md);" >&2
  echo "only a change the Sponsor permitted, run by the owner: DEPLOY_DURING_JUDGING=yes" >&2
  exit 1
fi

commit=$(git rev-parse HEAD) # once: a commit landing meanwhile must not change what is built
tag=$(git rev-parse --short=7 "$commit")
image="$acr.azurecr.io/matchlens:$tag"
revision="$app--$tag"

step() { echo "== $*"; }
# how many of `az <list command>`'s resources are named $1 (0 or 1). Run it as a plain
# assignment, `n=$(named ...)`: its status is az's, so a failed lookup (network, throttling)
# stops the script instead of passing for "missing", and a create never lands on a live resource
named() {
  local name=$1
  shift
  az "$@" --query "length([?name=='$name'])" -o tsv
}
# grants a role to the app's identity once (a second assignment of the same role is an error)
grant() {
  local role=$1 scope=$2 ids
  ids=$(az role assignment list --scope "$scope" --role "$role" \
    --query "[?principalId=='$principal'].id" -o tsv)
  if [ -n "$ids" ]; then
    echo "already granted"
  else
    az role assignment create --assignee-object-id "$principal" \
      --assignee-principal-type ServicePrincipal --role "$role" --scope "$scope" -o none
  fi
}

step "commit $tag on $(git rev-parse --abbrev-ref HEAD): $(git log -1 --format=%s "$commit")"

step "Log Analytics workspace $log"
n=$(named "$log" monitor log-analytics workspace list -g "$rg")
if [ "$n" = 0 ]; then
  az monitor log-analytics workspace create -g "$rg" -n "$log" -l "$location" --sku PerGB2018 \
    --retention-time 30 --tags "${tags[@]}" -o none
fi

step "registry $acr"
n=$(named "$acr" acr list -g "$rg")
if [ "$n" = 0 ]; then
  az acr create -g "$rg" -n "$acr" -l "$location" --sku Basic --admin-enabled false \
    --tags "${tags[@]}" -o none
fi
had_registry=$n # 0: created just now, so empty (its data plane may not answer a lookup yet)

step "image $image"
n=0
if [ "$had_registry" != 0 ]; then
  n=$(az acr repository list -n "$acr" --query "length([?@=='matchlens'])" -o tsv)
fi
if [ "$n" != 0 ]; then
  n=$(az acr repository show-tags -n "$acr" --repository matchlens \
    --query "length([?@=='$tag'])" -o tsv)
fi
if [ "$n" != 0 ]; then
  echo "already pushed"
else
  git archive --format=tar "$commit" | docker build --platform linux/amd64 -t "$image" -
  az acr login -n "$acr"
  docker push "$image"
fi

step "environment $env"
n=$(named "$env" containerapp env list -g "$rg")
if [ "$n" = 0 ]; then
  # the workspace's id only: the CLI looks up its key itself
  customer=$(az monitor log-analytics workspace show -g "$rg" -n "$log" --query customerId -o tsv)
  az containerapp env create -g "$rg" -n "$env" -l "$location" --logs-destination log-analytics \
    --logs-workspace-id "$customer" --tags "${tags[@]}" -o none
fi

step "app $app"
n=$(named "$app" containerapp list -g "$rg")
if [ "$n" = 0 ]; then
  # the CLI creates the app with a placeholder image, grants its new identity AcrPull on the
  # registry and then deploys the image: a first revision with ACA's default probes, which the
  # revision below replaces. On an existing app it would do the same (a PUT), hence the look
  az containerapp create -g "$rg" -n "$app" --environment "$env" --image "$image" \
    --registry-server "$acr.azurecr.io" --registry-identity system --system-assigned \
    --ingress external --target-port 8000 --tags "${tags[@]}" -o none
fi
principal=$(az containerapp show -g "$rg" -n "$app" --query identity.principalId -o tsv)
[ -n "$principal" ] || {
  echo "deploy.sh: $app has no system identity" >&2
  exit 1
}

# the scopes as variables: a failed lookup inside an argument would not stop the script
acr_id=$(az acr show -g "$rg" -n "$acr" --query id -o tsv)
foundry_id=$(az cognitiveservices account show -g "$rg" -n "$foundry" --query id -o tsv)

step "AcrPull for the app's identity on $acr"
grant AcrPull "$acr_id"

step "Foundry User for the app's identity on $foundry"
grant "$foundry_user" "$foundry_id"

step "revision $revision"
template_changed=0
git diff --quiet "$commit" -- deploy/containerapp.yaml || template_changed=1
n=$(named "$revision" containerapp revision list -g "$rg" -n "$app" --all)
if [ "$n" != 0 ]; then
  echo "already deployed"
  [ "$template_changed" = 0 ] ||
    echo "note: deploy/containerapp.yaml differs from $tag's; not applied (commit it first)" >&2
else
  [ "$template_changed" = 0 ] ||
    echo "note: deploy/containerapp.yaml differs from $tag's; the working tree's is applied" >&2
  spec=$(mktemp --suffix .yaml)
  trap 'rm -f "$spec"' EXIT
  sed -e "s|\${IMAGE}|$image|" -e "s|\${SUFFIX}|$tag|" deploy/containerapp.yaml >"$spec"
  az containerapp update -g "$rg" -n "$app" --yaml "$spec" -o none
fi
# until the revision is active and healthy; a failed one, an inactive one (an older commit's,
# deployed again) or the time limit ends the run with what may help
query='[properties.provisioningState, properties.runningState, properties.healthState, '\
'properties.active]'
t0=$(date +%s)
while :; do
  state=$(az containerapp revision show -g "$rg" -n "$app" --revision "$revision" \
    --query "$query" -o tsv | paste -sd ' ')
  waited=$(($(date +%s) - t0))
  echo "$waited s: $state"
  [ "$state" = "Provisioned Running Healthy true" ] && break
  if [[ "$state" == *false ]]; then
    echo "deploy.sh: $revision is not active: $state" >&2
    echo "(to go back to an older commit, git revert and deploy: docs/deploy.md, Roll back)" >&2
    exit 1
  fi
  if [[ "$state" == Failed* || "$state" == *" Failed "* ]] ||
    [ "$waited" -ge "$ready_limit_s" ]; then
    echo "deploy.sh: $revision not healthy after $waited s: $state" >&2
    echo "(restart it: az containerapp revision restart -g $rg -n $app --revision $revision)" >&2
    exit 1
  fi
  sleep 10
done
echo "$revision healthy (waited $(($(date +%s) - t0)) s)"
fqdn=$(az containerapp show -g "$rg" -n "$app" --query properties.configuration.ingress.fqdn -o tsv)
[ -n "$fqdn" ] || {
  echo "deploy.sh: $app has no ingress" >&2
  exit 1
}
echo "URL: https://$fqdn/"

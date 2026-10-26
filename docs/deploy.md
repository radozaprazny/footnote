# Deployment

Footnote (the package `matchlens`) runs as one container on Azure Container Apps and replays
the fictional matches m0, m1 and m3 with their logged Sonnet 5.5 runs (no model calls from the
container):

**https://ca-matchlens.niceglacier-670016e8.swedencentral.azurecontainerapps.io/**

Measurements (cold start, memory, streaming through the ingress, restarts, re-deploys) are in
`PROGRESS.md` (Metrics: Container, Readiness and stop, Deploy, Cost). Every command below runs from
the repo root with `az login` as the subscription's owner. Times in Azure's logs are UTC.

Who runs what: the read-only commands (health, logs, metrics, cost) anyone; a deploy, a restart and
the teardown change the published app, so only with the owner's OK.

## What runs where

All in resource group `rg-matchlens` (swedencentral), tagged as in `scripts/deploy.sh`:

| Resource | Name | Notes |
|---|---|---|
| Log Analytics workspace | `log-matchlens` | the environment's logs, 30 days |
| Container registry (Basic) | `acrmatchlens` | images `matchlens:<short sha>`, admin user off |
| Container Apps environment | `cae-matchlens` | Consumption; its domain is part of the URL |
| Container app | `ca-matchlens` | single revision mode, revisions `ca-matchlens--<short sha>` |
| Foundry account | `aif-matchlens` | from M3, not part of the deployment |

The app pulls from the registry with its system-assigned identity (`AcrPull` on `acrmatchlens`);
the same identity has Foundry User on `aif-matchlens` for live model calls later. The revision
template (size, scale, probes) is `deploy/containerapp.yaml`.

## Freeze during judging

From the submission's close (Wed 28 Oct 2026, 07:59 CET) to the end of judging (Wed 11 Nov 2026,
08:59 CET) the app must stay available and substantively the same as submitted (the hackathon's
Official Rules, 4.8 and 5). In that window: no re-deploy, not even a bug fix (owner, 24 Oct); a
restart if the app is unhealthy; a change only if the Sponsor permits it explicitly (Rule 5:
material that may infringe rights, personal data, anything inappropriate). `scripts/deploy.sh`
refuses to run in the window; for a change the Sponsor permitted the owner runs
`DEPLOY_DURING_JUDGING=yes scripts/deploy.sh`.

## Deploy and re-deploy

Commit, then from the branch the owner names (`main` once a milestone is merged there; it must
contain the freeze above, which came with M6 item 5):

```
scripts/deploy.sh
```

It prints the branch and the commit, creates whatever is missing, builds the image from the
commit (`git archive`, not the working tree), pushes it, puts a revision named after the commit
on, waits until it is active and healthy (each polled state printed, at most 600 s) and prints the
URL. A second run of the same commit changes nothing. The roll-over is gradual: the old revision
serves until the new one is ready, and an open page reconnects within seconds. A change to
`deploy/containerapp.yaml` takes effect only with a new commit.

App settings and environment variables go into the template (`env:` under the container): a
re-deploy replaces the container list, so a variable set only with `az containerapp update
--set-env-vars` is gone after the next commit's deploy.

If the script stops at a revision that failed, it prints the restart command. If it stops at an
inactive revision (an older commit deployed again), roll back as below instead.

## Roll back

Revert the bad commit, commit, and deploy: the revert's revision carries the old content.

```
git revert <commit>
scripts/deploy.sh
```

## Restart

```
az containerapp revision restart -g rg-matchlens -n ca-matchlens --revision "$(az containerapp show -g rg-matchlens -n ca-matchlens --query properties.latestReadyRevisionName -o tsv)"
```

This restarts the revision that serves. A new replica starts first; the old one stops once it is
ready, so the URL keeps answering.

## Health

```
url="https://$(az containerapp show -g rg-matchlens -n ca-matchlens --query properties.configuration.ingress.fqdn -o tsv)"
curl -s "$url/readyz"
az containerapp revision list -g rg-matchlens -n ca-matchlens -o table
```

`/healthz` answers as soon as the server is up; `/readyz` only once every match's cue timeline is
computed (503 with the pending matches before). Only the readiness probe asks `/readyz`.

## Logs

The server's own output, streamed:

```
az containerapp logs show -g rg-matchlens -n ca-matchlens --type console --follow --format text
```

The platform's events (image pulls, probe failures, replicas starting and stopping):

```
az containerapp logs show -g rg-matchlens -n ca-matchlens --type system --tail 50
```

Older logs, from Log Analytics (tables `ContainerAppConsoleLogs_CL` and
`ContainerAppSystemLogs_CL`). `az monitor log-analytics query` needs a preview extension; the REST
call does not:

```
cid=$(az monitor log-analytics workspace show -g rg-matchlens -n log-matchlens --query customerId -o tsv)
az rest --method get --resource https://api.loganalytics.io --url "https://api.loganalytics.io/v1/workspaces/$cid/query" --url-parameters "query=ContainerAppConsoleLogs_CL | where TimeGenerated > ago(1h) | where not(Log_s has 'GET /healthz' or Log_s has 'GET /readyz') | project TimeGenerated, RevisionName_s, Log_s" --query "tables[0].rows" -o tsv
```

Memory, CPU and replicas per minute:

```
az monitor metrics list --resource "$(az containerapp show -g rg-matchlens -n ca-matchlens --query id -o tsv)" --metric WorkingSetBytes UsageNanoCores Replicas --interval PT1M --offset 1h --aggregation Maximum -o table
```

## Cost

The resource group's charges per day and meter, in EUR, here for October (rows appear hours
late; Container Apps use inside its monthly free grant costs nothing). `az consumption usage list`
returns these rows without quantities or costs on this subscription, so the REST call:

```
az rest --method get --url "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/providers/Microsoft.Consumption/usageDetails" --url-parameters api-version=2023-05-01 startDate=2026-10-01 endDate=2026-10-31 --query 'value[?properties.resourceGroup == `"rg-matchlens"`].{date: properties.date, meter: properties.meterName, quantity: properties.quantity, eur: properties.costInBillingCurrency}' -o table
```

The rows whose meter names Claude are the models on Foundry, billed per call: today the agents'
runs from the devbox, the deployment's own cost once the app calls models itself.

## Teardown

After the judging period, only with the owner's OK. In this order: the identity's role
assignments first (deleting the app leaves them behind, orphaned), the app before its
environment:

```
principal=$(az containerapp show -g rg-matchlens -n ca-matchlens --query identity.principalId -o tsv)
az role assignment delete --ids $(az role assignment list --all --query "[?principalId=='$principal'].id" -o tsv)
az containerapp delete -g rg-matchlens -n ca-matchlens --yes
az containerapp env delete -g rg-matchlens -n cae-matchlens --yes
az acr delete -g rg-matchlens -n acrmatchlens --yes
az monitor log-analytics workspace delete -g rg-matchlens -n log-matchlens --yes --force true
```

(`--force true`: without it the workspace stays soft-deleted for 14 days and keeps its name.)
Afterwards `az resource list -g rg-matchlens -o table` lists only `aif-matchlens` and its project.

Never delete the resource group (it holds the Foundry account) or `aif-matchlens`. Never delete
and create `cae-matchlens` again while the URL is published: the part of the URL after
`ca-matchlens.` belongs to the environment, and a new one gets a new URL.

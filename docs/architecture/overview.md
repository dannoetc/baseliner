# Architecture overview

Baseliner is an MVP for “baseline state management”:

- Admin defines **policies**
- Devices enroll and receive an **effective policy**
- Agent runs checks/remediations and posts **runs/reports**

## Components

- **Server (FastAPI)**: device enrollment, policy assignment, effective policy compilation, run ingestion
- **Agent**: polls for policy, executes resources, reports results, produces support bundles
- **DB (Postgres)**: stores devices, policies, assignments, runs, audit logs

## TODO

- Add request/response diagrams for enrollment and reporting
- Add “policy compilation” semantics reference (first-wins by (type,id), ordered by priority)

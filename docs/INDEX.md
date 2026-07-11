# Documentation Index

## Getting Started

| Doc | Audience | Description |
|-----|----------|-------------|
| [README.md](../README.md) | all | Project orientation, pipeline overview, roadmap |
| [End-to-End Tutorial](end-to-end-tutorial.md) | adopter | Step-by-step walkthrough from profiling to import |
| [Contributing](contributing.md) | contributor | Dev setup, test suite, PR expectations |

## Architecture & Design

| Doc | Audience | Description |
|-----|----------|-------------|
| [Architecture](architecture.md) | all | Five-layer design, data flow, Django project layout |
| [Schema Design Loop](schema-design-loop.md) | adopter | Contract-first importer workflow |
| [Schema Contract Reference](schema-contract.md) | adopter | YAML contract format reference |
| [View Manifest Reference](view-manifest.md) | adopter | Codegen manifest YAML format, admin generation effects |
| [Interaction Contract](interaction-contract.md) | adopter | Three-layer UI/workflow contract: profiler signals, human contract, codegen manifest |
| [Pipeline State](pipeline-state.md) | implementer | Layered profiler runtime state and checkpoint design |
| [Pipeline Manifest Reference](pipeline-manifest.md) | operator | Machine-generated execution plan format |
| [Roadmap](roadmap.md) | all | Milestone history and direction (0.5.3 shipped, two tracks on 1.0.0) |
| [Agent Harness](agent-harness.md) | all | Design philosophy: agent does everything that does not require judgment, alerting the human for the judgment |

## Operations

| Doc | Audience | Description |
|-----|----------|-------------|
| [Deployment](deployment.md) | operator | Fly.io, Litestream, CI/CD, health checks |
| [Pull Bundle Guide](pull-bundle.md) | operator | Source config, live/offline modes, bundle validation |
| [Google Auth](google-auth.md) | operator | Sheets/Drive profiling auth setup |
| [Google Corpus](google-corpus.md) | operator | Multi-workbook Drive folder profiling |
| [Coda](coda.md) | operator | Coda profiling |
| [Troubleshooting](troubleshooting.md) | all | Consolidated FAQ for common errors |

## Per-Package READMEs

| Doc | App | Description |
|-----|-----|-------------|
| [connectors/README.md](../connectors/README.md) | connectors | Provider adapter surfaces |
| [profiler/README.md](../profiler/README.md) | profiler | Profiling commands and artifacts |
| [importer/README.md](../importer/README.md) | importer | Import chassis and summary JSON |
| [workbook/README.md](../workbook/README.md) | workbook | Schema contract and codegen |
| [deployment/README.md](../deployment/README.md) | deployment | CLI and manifest validation |

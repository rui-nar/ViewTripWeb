## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

## testing
ensure tests are available for every feature to ensure non-regressions

## versioning
version are standard x.y.z where y is for features and z is for patches. unless instructed otherwise, bumping a release means to increase the feature version. there is a github repository with github actions to automatically generate docker images so every verison bump shall also be tagged as latest

## current stack
current stack is compoesed of a sever in python FastAPI serving clients written in flutter for  web, android and iOS. any architecutre decision shall keep this structure in mind.
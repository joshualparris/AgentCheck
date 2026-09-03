$ErrorActionPreference = 'Stop'
$agentWitness = 'C:\dev\LLMLieDetector\AgentWitness'
$aw = Join-Path $agentWitness 'venv\Scripts\aw.exe'
$state = 'C:\dev\automation-state\forgegrid-chess'
$goal = Join-Path $state 'goal.md'

& $aw supervise `
  --goal-file $goal `
  --workspace 'C:\dev\Chess\github-current' `
  --state-dir $state `
  --conversation-id '80dbeb67-fccb-4dea-82cf-c704238557ed' `
  --evidence-repo 'C:\dev\Chess\github-current' `
  --evidence-repo 'C:\dev\GithubActions\ForgeGrid' `
  --evidence-repo 'C:\dev\6 Laptops\ForgeGrid' `
  --evidence-repo 'C:\dev\AI-Verification\AgentCheck' `
  --evidence-repo 'C:\dev\LLMLieDetector\AgentWitness' `
  --max-cycles 40 `
  --max-total-tokens 1500000 `
  --max-cost-usd 150 `
  --retry-human-required

exit $LASTEXITCODE

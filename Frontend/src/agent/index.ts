/**
 * The composition root for the agent: the backend's Claude agent in real mode, the scripted stand-in over
 * the fixtures in mock mode. Both are AgentRunners, so the rest of the app doesn't know which it has.
 */
import { agentApi, backend, callMeta, MOCK_LOCATIONS_HINT, USE_MOCK } from "../api";
import type { AgentContext, AgentTurnResult } from "../types";
import { createRemoteAgent } from "./remote";
import type { AgentRunner, StepListener } from "./runner";
import { createScriptedAgent } from "./scripted";

export type { AgentRunner, StepListener } from "./runner";

const runner: AgentRunner = USE_MOCK
  ? createScriptedAgent(backend, { cacheStatus: () => callMeta.cache, unknownPlaceHint: MOCK_LOCATIONS_HINT })
  : createRemoteAgent(agentApi, backend);

/** Runs one agent turn with whichever agent this build uses. */
export function runAgentTurn(message: string, context: AgentContext, onSteps: StepListener): Promise<AgentTurnResult> {
  return runner.run(message, context, onSteps);
}

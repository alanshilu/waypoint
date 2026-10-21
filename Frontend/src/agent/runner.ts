import type { AgentContext, AgentTurnResult, StepView } from "../types";

export type StepListener = (steps: StepView[]) => void;

/**
 * Runs one agent turn: answers the message, reports each tool call through onSteps as it runs, and returns
 * what changed. The backend agent (remote.ts) and the scripted mock (scripted.ts) both implement it.
 */
export interface AgentRunner {
  run(message: string, context: AgentContext, onSteps: StepListener): Promise<AgentTurnResult>;
}

/**
 * OpenCode lifecycle plugin — registers hooks and dispatches stdin to Python lifecycle
 * (PRD 349 R26–R28 + PRD 352 R4/R5).
 */

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

export type UnsupportedEventDiagnostic = {
  code: "unsupported_event";
  canonical: string;
  message: string;
};

export type HookRegistration = {
  hostEvent: string;
  canonical: string;
  handler: string;
};

type LifecyclePluginOptions = {
  handlers: HookRegistration[];
  unsupported: UnsupportedEventDiagnostic[];
};

const pluginDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * Process host event stdin via the Python lifecycle handler (never exit 0 without
 * consuming stdin — PRD 352 R5).
 */
export function dispatchLifecycleStdin(stdin: string, argv: string[] = []): {
  status: number;
  stdout: string;
  stderr: string;
} {
  const lifecyclePy = path.join(pluginDir, "lifecycle.py");
  const result = spawnSync("python3", [lifecyclePy, ...argv], {
    input: stdin,
    encoding: "utf-8",
  });
  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

/**
 * Register supported lifecycle handlers and emit structured diagnostics for
 * unsupported events — never silently skip (R28).
 */
export function registerLifecycleHooks(options: LifecyclePluginOptions): {
  registered: string[];
  diagnostics: UnsupportedEventDiagnostic[];
} {
  const registered: string[] = [];
  for (const handler of options.handlers) {
    registered.push(handler.hostEvent);
  }
  const diagnostics = [...options.unsupported];
  for (const diagnostic of diagnostics) {
    console.warn(JSON.stringify({ type: "shipwright.unsupported_event", ...diagnostic }));
  }
  return { registered, diagnostics };
}

export const packageMechanism = "opencode-plugin";
export const distinctFromClaudePlugin = true;

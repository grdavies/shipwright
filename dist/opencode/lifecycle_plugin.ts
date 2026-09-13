/**
 * OpenCode lifecycle plugin — thin hook-registration shim only (PRD 349 R26–R28).
 * Skill and command logic stay in core Python/Markdown sources.
 */

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

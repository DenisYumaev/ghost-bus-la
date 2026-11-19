/**
 * Every user-facing string lives in `messages/` (web spec section 9), so a translation is a new
 * file, not a code change. Keys are checked at compile time.
 */
import en from "@/messages/en.json";

export type MessageKey = keyof typeof en;

export function t(key: MessageKey, vars: Record<string, string | number> = {}): string {
  return en[key].replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

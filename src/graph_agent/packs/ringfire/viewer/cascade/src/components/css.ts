import type { CSSProperties } from "react";

/** Style with the `--c` colour variable the stylesheet uses for tags, keys and legend marks. */
export const c = (colour: string, rest: CSSProperties = {}): CSSProperties =>
  ({ "--c": colour, ...rest }) as CSSProperties;

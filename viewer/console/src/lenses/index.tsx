// A lens is how the console draws a pack's world on the side screen (like the Fire game's "Real
// world" panel). The server names it in `world.lens`; to add a pack's own view, add a file here.
import type { ReactElement } from "react";
import type { RunEvent, SpaceState } from "../types";
import { AppsBody, describeApps } from "./apps";
import { describeLife, LifeBody } from "./life";
import { describeReal, RealBody } from "./real";
import { describeQuake, QuakeBody } from "./hualien";
import { describeOffsite, OffsiteBody } from "./offsite";
import { describeFire, FireBody } from "./ringfire";

export interface Lens {
  eyebrow: string;
  title: string;
  Body: (props: { space: SpaceState }) => ReactElement;
  describe: (event: RunEvent) => string | undefined; // the pack's own event kinds, in plain words
}

export const LENSES: Record<string, Lens> = {
  life: { eyebrow: "Ground truth · agents only see it through tools", title: "The week", Body: LifeBody, describe: describeLife },
  ringfire: { eyebrow: "Ground truth · agents never see this", title: "Real world", Body: FireBody, describe: describeFire },
  offsite: { eyebrow: "Ground truth · agents only see it through tools", title: "The offsite", Body: OffsiteBody, describe: describeOffsite },
  hualien: { eyebrow: "Ground truth · real figures, invented fabs", title: "The quake", Body: QuakeBody, describe: describeQuake },
  real: { eyebrow: "Your accounts · read-only", title: "What it has read", Body: RealBody, describe: describeReal },
  apps: { eyebrow: "Your apps", title: "What it has read", Body: AppsBody, describe: describeApps },
};

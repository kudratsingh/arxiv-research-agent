/**
 * WO-06 — the global decorator surface, in one import.
 *
 * Every export here is wired into .storybook/preview.tsx once. A story
 * author writes nothing: declaring a `meta` and a `StoryObj` is enough to
 * get all three toolbars (theme, viewport, reduced motion) and the axe run.
 * There is no per-story opt-in and no per-story wiring anywhere in this
 * work order or the ones that follow it.
 */

export {
  DEFAULT_THEME,
  FORCED_COLORS_ATTRIBUTE,
  THEME_GLOBAL,
  THEME_OPTIONS,
  themeGlobalType,
  withTheme,
  type StorybookTheme,
} from "./theme";

export {
  DEFAULT_MOTION,
  MOTION_GLOBAL,
  MOTION_OPTIONS,
  REDUCED_MOTION_ATTRIBUTE,
  motionGlobalType,
  withReducedMotion,
  type MotionPreference,
} from "./reducedMotion";

export { RC14_WIDTHS, VIEWPORTS, type ViewportKey } from "./viewport";

export { FONT_VARIABLE_CLASSES, withFonts } from "./fonts";

export const VIEWPORTS = {
  mobile_small: { width: 320, height: 568 },   // iPhone SE
  mobile_medium: { width: 375, height: 667 },  // iPhone 8
  mobile_large: { width: 414, height: 896 },   // iPhone 11
  tablet: { width: 768, height: 1024 },         // Tablet boundary
  desktop: { width: 1280, height: 800 },
  desktop_wide: { width: 1440, height: 900 },
} as const;

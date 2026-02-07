/**
 * Device detection utility for adaptive rendering.
 * Provides simple checks for mobile, screen size, and device capabilities.
 */
const Device = {
    isMobile() {
        return window.innerWidth <= 768 || navigator.maxTouchPoints > 0;
    },

    isSmallScreen() {
        return window.innerWidth <= 480;
    },

    prefersReducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    },

    hasLowMemory() {
        return navigator.deviceMemory !== undefined && navigator.deviceMemory <= 4;
    },

    pixelRatio() {
        return window.devicePixelRatio || 1;
    }
};

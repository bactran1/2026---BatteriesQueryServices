# Vendored Three.js

This directory contains the browser modules required by the battery monitor's
3D energy-flow scene.

- Package: `three`
- Version: `0.185.1`
- Source: `https://www.npmjs.com/package/three/v/0.185.1`
- Package integrity: `sha512-5aojFCXKwnjBRZvUnt3WFfEcvUJgkN5LlijRFN95hMy8WVkG4I0QNcJE+OuWvuJ0bOdStrbfXn0pkd6/QyiAlg==`
- Files: `build/three.module.min.js` and `build/three.core.min.js`
- License: MIT; see `three-LICENSE.txt`

The `jsm/` subdirectory holds the postprocessing add-ons the energy-flow scene
uses for its UnrealBloomPass glow, copied unmodified from the same release
(`examples/jsm/`):

- `jsm/postprocessing/`: `EffectComposer.js`, `Pass.js`, `RenderPass.js`,
  `ShaderPass.js`, `MaskPass.js`, `UnrealBloomPass.js`, `OutputPass.js`
- `jsm/shaders/`: `CopyShader.js`, `LuminosityHighPassShader.js`,
  `OutputShader.js`

They resolve through the `"three/addons/" -> "/static/vendor/jsm/"` import-map
entry in `index.html`. To refresh, recopy the matching files from
`three@0.185.1/examples/jsm/` preserving this layout.

The files are served locally so the deployed dashboard does not depend on a
third-party CDN at runtime.

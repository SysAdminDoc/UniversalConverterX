# Client-side GIF editing: A complete JavaScript library guide

Building a browser-based GIF editor for GitHub Pages is entirely feasible using mature JavaScript libraries. The optimal stack combines **gifuct-js** for decoding with **gif.js** (or **gifenc** for speed) for encoding, wrapped around Canvas API manipulation. All required functionality—importing, cropping, resizing, frame editing, and exporting—can run entirely client-side with no backend.

## The recommended library stack

For a complete GIF editing pipeline, two libraries form the foundation: **gifuct-js** handles decoding/parsing existing GIFs into manipulable frames, while **gif.js** reconstructs edited frames into a new GIF file. This combination covers all five required features with well-documented APIs and proven stability.

**gifuct-js** (498 GitHub stars, ~432K weekly NPM downloads) provides the cleanest modern API for extracting frames from GIF files. It outputs canvas-ready `Uint8ClampedArray` patches with full metadata including frame dimensions, delay timing, disposal methods, and transparency handling. The library is drawing-agnostic—you receive pure pixel data to render however you choose.

**gif.js** (4,900 stars, used by 1,300+ projects) remains the most battle-tested encoding solution. Its Web Worker architecture prevents UI blocking during CPU-intensive color quantization, and built-in dithering options (Floyd-Steinberg, Atkinson, Stucki) handle photographic content well. For vector graphics or when speed matters more than dithering quality, **gifenc** offers **2x faster encoding** at ~9KB bundle size.

| Library | Purpose | Weekly Downloads | Key Strength |
|---------|---------|------------------|--------------|
| gifuct-js | Decode/parse GIFs | ~432K | Canvas-ready frame patches |
| gif.js | Encode GIFs | ~12.5K | Dithering + Web Workers |
| gifenc | Fast encoding | ~1K | 2x faster, 9KB size |
| omggif | Encode + decode | ~1.5M | Foundation library |

## Decoding pipeline: From GIF file to editable frames

The decoding process transforms a binary GIF into an array of frame objects that can be rendered to canvas and manipulated:

```javascript
import { parseGIF, decompressFrames } from 'gifuct-js';

async function loadGif(file) {
  const buffer = await file.arrayBuffer();
  const gif = parseGIF(buffer);
  const frames = decompressFrames(gif, true); // true = build canvas patches
  
  return frames.map(frame => ({
    imageData: new ImageData(
      new Uint8ClampedArray(frame.patch),
      frame.dims.width,
      frame.dims.height
    ),
    delay: frame.delay,
    offset: { x: frame.dims.left, y: frame.dims.top }
  }));
}
```

Each frame contains `pixels` (color table indices), `dims` (position and size), `delay` (milliseconds), `disposalType` (how to clear before next frame), `colorTable`, and critically, `patch`—a pre-computed RGBA array ready for `ImageData` construction. The `cumulative` rendering consideration matters: many GIFs contain partial frames that layer on previous frames, requiring proper disposal handling.

## Canvas-based frame manipulation

All editing operations—cropping, resizing, and pixel modification—use the Canvas 2D API. For frequent `getImageData` calls, initialize context with `{ willReadFrequently: true }` to optimize performance:

```javascript
// Cropping
function cropFrame(sourceCanvas, cropRect) {
  const cropped = document.createElement('canvas');
  cropped.width = cropRect.width;
  cropped.height = cropRect.height;
  const ctx = cropped.getContext('2d');
  ctx.drawImage(sourceCanvas, 
    cropRect.x, cropRect.y, cropRect.width, cropRect.height,
    0, 0, cropRect.width, cropRect.height
  );
  return cropped;
}

// Resizing
function resizeFrame(sourceCanvas, newWidth, newHeight) {
  const resized = document.createElement('canvas');
  resized.width = newWidth;
  resized.height = newHeight;
  const ctx = resized.getContext('2d');
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(sourceCanvas, 0, 0, newWidth, newHeight);
  return resized;
}
```

For frame deletion, simply remove the frame from your frames array. For frame reordering, splice the array. The Canvas API handles all pixel-level operations efficiently—use `Math.floor()` on all coordinates to avoid expensive sub-pixel anti-aliasing.

## Encoding pipeline: Frames back to GIF

The encoding process with gif.js uses Web Workers to prevent UI freezing:

```javascript
function encodeGif(frames, width, height) {
  return new Promise((resolve, reject) => {
    const gif = new GIF({
      workers: 2,
      quality: 10,  // 1-30, lower = better quality
      width, height,
      workerScript: 'gif.worker.js'
    });
    
    frames.forEach(frame => {
      gif.addFrame(frame.canvas, { delay: frame.delay, copy: true });
    });
    
    gif.on('progress', p => updateProgressBar(p * 100));
    gif.on('finished', blob => resolve(blob));
    gif.on('error', reject);
    gif.render();
  });
}
```

The `quality` parameter controls NeuQuant neural network sampling—lower values produce better color reproduction but slower encoding. For the alternative **gifenc** approach (faster, no built-in dithering):

```javascript
import { GIFEncoder, quantize, applyPalette } from 'gifenc';

const gif = GIFEncoder();
frames.forEach(frame => {
  const { data } = frame.ctx.getImageData(0, 0, width, height);
  const palette = quantize(data, 256);
  const index = applyPalette(data, palette);
  gif.writeFrame(index, width, height, { palette, delay: frame.delay });
});
gif.finish();
const blob = new Blob([gif.bytes()], { type: 'image/gif' });
```

## Reference implementations worth studying

**han1548772930/gif_player** (https://github.com/han1548772930/gif_player) provides the most complete open-source reference—a Vue.js/TypeScript GIF editor with frame navigation, trimming, text overlays, and export. It uses FFmpeg WASM for parsing and demonstrates a modern component architecture. Live demo at han1548772930.netlify.app.

**mattdesl/gif-extractor** (https://github.com/mattdesl/gif-extractor) offers a cleaner, minimal vanilla JavaScript example for frame extraction with optional upscaling. It demonstrates gifuct-js integration and the Chrome File System API for saving. The codebase is small enough to understand completely.

**jnordberg/gif.js demo** (https://jnordberg.github.io/gif.js/) showcases encoding capabilities with real-time progress reporting and quality/dithering controls—useful for understanding encoding parameters.

## Memory management for large GIFs

A **1024×1024 frame requires ~4MB** of raw RGBA data. A 100-frame GIF at this resolution consumes ~400MB just for pixel data. Critical strategies:

- **Process frames sequentially** rather than loading all simultaneously
- **Release references immediately** after processing (`frame = null`)
- **Use transferable objects** in Worker communication to avoid copying
- **Implement frame caching** with LRU eviction (keep ~20 recent frames)
- **Generate thumbnails** for timeline display at reduced resolution

```javascript
// Transfer ArrayBuffer to worker without copying
const buffer = imageData.data.buffer;
worker.postMessage({ buffer }, [buffer]); // Second param = transfer list
```

For persistent storage during editing sessions, IndexedDB handles large binary data efficiently—store frames as Blobs (not base64 strings) and never index binary columns. Safari deletes stale IndexedDB after 7 days without user interaction.

## Color quantization and dithering matter

GIF's **256-color limit** makes quantization quality critical for photographic content. The NeuQuant algorithm (used by gif.js) favors smooth gradients. PnnQuant (used by gifenc) is faster but produces slightly different results. For photos, **dithering is essential**—Floyd-Steinberg with serpentine scanning reduces banding artifacts significantly.

| Algorithm | Library | Best For |
|-----------|---------|----------|
| NeuQuant | gif.js, Animated_GIF | Photographs, gradients |
| PnnQuant | gifenc | Speed, vector graphics |
| Median Cut | quantize.js | General purpose |

## Minimal GitHub Pages implementation

For a static site, CDN-hosted libraries eliminate build complexity:

```html
<script src="https://unpkg.com/gifuct-js@1.0.0/dist/gifuct-js.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.js"></script>
```

The complete pipeline: File input → ArrayBuffer → gifuct-js parse → Canvas frames array → User edits via Canvas API → gif.js encode → Blob → Download link via `URL.createObjectURL()`. No server required.

## Conclusion: Proven path forward

The JavaScript GIF ecosystem is mature despite limited recent maintenance—the GIF spec is stable, and libraries like gif.js and gifuct-js remain fully functional. The recommended approach pairs gifuct-js decoding with gif.js encoding, using Canvas 2D API for all manipulation. Study the gif_player Vue reference for architecture patterns, or gif-extractor for minimal vanilla JS. For performance-critical applications encoding many large frames, gifenc's 2x speed improvement and small bundle justify the lack of built-in dithering. All libraries work entirely client-side and deploy seamlessly to GitHub Pages.
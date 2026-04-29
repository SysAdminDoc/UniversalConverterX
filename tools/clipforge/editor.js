// ==================== GLOBAL STATE ====================
let ffmpeg = null, ffmpegLoaded = false;
let mediaItems = []; // Imported media files
let clips = []; // Clips on timeline
let transitions = []; // Transitions between clips
let selectedClips = []; // Currently selected clips
let clipboard = null; // Copied clip data
let currentTool = 'select';
let currentTransitionType = 'dissolve';

// Playback state
let isPlaying = false;
let currentTime = 0; // in seconds
let duration = 0;
let playbackInterval = null;

// Timeline state
let pixelsPerSecond = 50; // Zoom level
let timelineOffset = 0;
let draggingClip = null;
let draggingHandle = null;
let isDraggingPlayhead = false;

// Audio context for waveforms
let audioContext = null;

// Preview elements
let previewVideo, previewCanvas, previewCtx;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', async () => {
    previewVideo = document.getElementById('previewVideo');
    previewCanvas = document.getElementById('previewCanvas');
    previewCtx = previewCanvas?.getContext('2d');
    
    setupEventListeners();
    renderRuler();
    await initFFmpeg();
});

async function initFFmpeg() {
    await window.coiReady;
    
    if (typeof SharedArrayBuffer === 'undefined') {
        document.getElementById('loadingText').textContent = 'Refresh required';
        document.getElementById('loadingOverlay').innerHTML = `
            <div style="text-align: center;">
                <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                <div style="font-size: 14px; margin-bottom: 16px; color: var(--text-1);">Please refresh to initialize</div>
                <button class="btn primary" onclick="location.reload()">Refresh Page</button>
            </div>
        `;
        return;
    }
    
    try {
        const { createFFmpeg, fetchFile } = FFmpeg;
        ffmpeg = createFFmpeg({
            log: true,
            corePath: 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.10.0/dist/ffmpeg-core.js',
            progress: ({ ratio }) => {
                const pct = Math.round(ratio * 100);
                document.getElementById('loadingProgress').style.width = pct + '%';
            }
        });
        window.ffmpegFetchFile = fetchFile;
        
        document.getElementById('loadingText').textContent = 'Loading FFmpeg engine...';
        await ffmpeg.load();
        
        ffmpegLoaded = true;
        document.getElementById('loadingOverlay').classList.add('hidden');
        document.getElementById('statusDot').classList.add('ready');
        document.getElementById('statusText').textContent = 'Ready';
        
        toast('success', 'ClipForge ready!');
    } catch (e) {
        console.error('FFmpeg load error:', e);
        document.getElementById('loadingText').textContent = 'Failed to load FFmpeg';
        toast('error', 'Failed to initialize FFmpeg');
    }
}

// ==================== EVENT LISTENERS ====================
function setupEventListeners() {
    // File input
    document.getElementById('fileInput').addEventListener('change', handleFileInput);
    
    // Drop zone
    const dropZone = document.getElementById('dropZone');
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('drag-over'); handleFileDrop(e.dataTransfer.files); });
    
    // Timeline interactions
    const tracksContainer = document.getElementById('tracksContainer');
    tracksContainer.addEventListener('mousedown', onTimelineMouseDown);
    tracksContainer.addEventListener('mousemove', onTimelineMouseMove);
    tracksContainer.addEventListener('mouseup', onTimelineMouseUp);
    tracksContainer.addEventListener('mouseleave', onTimelineMouseUp);
    tracksContainer.addEventListener('wheel', onTimelineWheel, { passive: false });
    
    // Ruler click for playhead
    document.getElementById('timelineRuler').addEventListener('mousedown', onRulerClick);
    
    // Context menu
    document.addEventListener('contextmenu', onContextMenu);
    document.addEventListener('click', () => document.getElementById('contextMenu').classList.remove('visible'));
    
    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyboard);
    
    // Preview video events
    previewVideo.addEventListener('timeupdate', onVideoTimeUpdate);
    previewVideo.addEventListener('loadedmetadata', onVideoLoaded);
    previewVideo.addEventListener('ended', onVideoEnded);
    
    // Panel tabs
    document.querySelectorAll('.panel-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            tab.parentElement.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
        });
    });
    
    // Media list drag
    document.getElementById('mediaList').addEventListener('dragstart', onMediaDragStart);
}

function handleKeyboard(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    
    const key = e.key.toLowerCase();
    
    // Tool shortcuts
    if (key === 'v') setTool('select');
    if (key === 'c' && !e.ctrlKey) setTool('razor');
    if (key === 'y') setTool('slip');
    if (key === 'h') setTool('hand');
    
    // Playback
    if (key === ' ') { e.preventDefault(); togglePlay(); }
    if (key === 'j') stepBackward();
    if (key === 'k') togglePlay();
    if (key === 'l') stepForward();
    if (key === 'home') goToStart();
    if (key === 'end') goToEnd();
    if (key === 'arrowleft') { currentTime = Math.max(0, currentTime - 1/30); updatePlayhead(); }
    if (key === 'arrowright') { currentTime = Math.min(duration, currentTime + 1/30); updatePlayhead(); }
    
    // Editing
    if (key === 's' && !e.ctrlKey) splitClip();
    if (key === 'delete' || key === 'backspace') deleteSelected();
    if (e.ctrlKey && key === 'c') copyClip();
    if (e.ctrlKey && key === 'x') cutClip();
    if (e.ctrlKey && key === 'v') pasteClip();
    if (e.ctrlKey && key === 'a') { e.preventDefault(); selectAllClips(); }
    if (e.ctrlKey && key === 'z') undo();
    if (e.ctrlKey && key === 's') { e.preventDefault(); saveProject(); }
}

// ==================== MEDIA IMPORT ====================
function handleFileInput(e) {
    handleFileDrop(e.target.files);
}

async function handleFileDrop(files) {
    for (const file of files) {
        const type = getMediaType(file);
        if (!type) continue;
        
        const media = {
            id: Date.now() + Math.random(),
            file,
            name: file.name,
            type,
            duration: 0,
            thumbnail: null,
            waveform: null,
            url: URL.createObjectURL(file)
        };
        
        // Get duration and generate thumbnail/waveform
        if (type === 'video' || type === 'audio') {
            await loadMediaMetadata(media);
        } else if (type === 'image') {
            media.duration = 5; // Default 5 seconds for images
            media.thumbnail = media.url;
        }
        
        mediaItems.push(media);
    }
    
    renderMediaList();
    toast('success', `Imported ${files.length} file(s)`);
}

function getMediaType(file) {
    if (file.type.startsWith('video/')) return 'video';
    if (file.type.startsWith('audio/')) return 'audio';
    if (file.type.startsWith('image/')) return 'image';
    
    const ext = file.name.split('.').pop().toLowerCase();
    if (['mp4', 'webm', 'mkv', 'avi', 'mov', 'flv'].includes(ext)) return 'video';
    if (['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'].includes(ext)) return 'audio';
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'].includes(ext)) return 'image';
    
    return null;
}

async function loadMediaMetadata(media) {
    return new Promise((resolve) => {
        const element = media.type === 'video' ? document.createElement('video') : document.createElement('audio');
        element.src = media.url;
        element.preload = 'metadata';
        
        element.onloadedmetadata = async () => {
            media.duration = element.duration;
            
            if (media.type === 'video') {
                // Generate thumbnail
                element.currentTime = Math.min(1, element.duration / 4);
                element.onseeked = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 160;
                    canvas.height = 90;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(element, 0, 0, canvas.width, canvas.height);
                    media.thumbnail = canvas.toDataURL();
                    media.width = element.videoWidth;
                    media.height = element.videoHeight;
                    resolve();
                };
            } else {
                // Generate waveform for audio
                try {
                    media.waveform = await generateWaveform(media.file);
                } catch (e) {
                    console.warn('Waveform generation failed:', e);
                }
                resolve();
            }
        };
        
        element.onerror = () => {
            console.error('Failed to load media:', media.name);
            resolve();
        };
    });
}

async function generateWaveform(file) {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    const arrayBuffer = await file.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    
    const rawData = audioBuffer.getChannelData(0);
    const samples = 200; // Number of samples for waveform
    const blockSize = Math.floor(rawData.length / samples);
    const waveformData = [];
    
    for (let i = 0; i < samples; i++) {
        let sum = 0;
        for (let j = 0; j < blockSize; j++) {
            sum += Math.abs(rawData[i * blockSize + j]);
        }
        waveformData.push(sum / blockSize);
    }
    
    // Normalize
    const max = Math.max(...waveformData);
    return waveformData.map(v => v / max);
}

function renderMediaList() {
    const list = document.getElementById('mediaList');
    
    if (mediaItems.length === 0) {
        list.innerHTML = `
            <div style="text-align: center; padding: 40px 20px; color: var(--text-3);">
                <div style="font-size: 32px; margin-bottom: 12px;">📂</div>
                <div style="font-size: 12px;">No media imported</div>
            </div>
        `;
        return;
    }
    
    list.innerHTML = mediaItems.map(media => `
        <div class="media-item" data-id="${media.id}" draggable="true" ondblclick="addToTimeline('${media.id}')">
            <div class="media-thumb">
                ${media.thumbnail ? 
                    (media.type === 'video' ? `<img src="${media.thumbnail}">` : `<img src="${media.thumbnail}">`) :
                    `<span class="media-thumb-icon">${media.type === 'audio' ? '🎵' : '📷'}</span>`
                }
            </div>
            <div class="media-info">
                <div class="media-name">${media.name}</div>
                <div class="media-meta">
                    <span>${media.type}</span>
                    <span class="media-duration">${formatTimecode(media.duration)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// ==================== TIMELINE CLIPS ====================
function addToTimeline(mediaId) {
    const media = mediaItems.find(m => m.id == mediaId);
    if (!media) return;
    
    // Find the end of existing clips
    const track = media.type === 'audio' ? 'music' : 'video';
    const trackClips = clips.filter(c => c.track === track);
    const startTime = trackClips.length > 0 ? Math.max(...trackClips.map(c => c.startTime + c.duration)) : 0;
    
    const clip = {
        id: Date.now() + Math.random(),
        mediaId: media.id,
        track,
        startTime,
        duration: media.duration,
        inPoint: 0,
        outPoint: media.duration,
        name: media.name,
        type: media.type,
        thumbnail: media.thumbnail,
        waveform: media.waveform,
        url: media.url,
        // Effects
        opacity: 100,
        scale: 100,
        rotation: 0,
        brightness: 0,
        contrast: 0,
        saturation: 0,
        volume: 100
    };
    
    // If video, also add linked audio clip
    if (media.type === 'video') {
        const audioClip = {
            ...clip,
            id: Date.now() + Math.random() + 1,
            track: 'audio',
            type: 'audio',
            linkedTo: clip.id
        };
        clip.linkedTo = audioClip.id;
        clips.push(audioClip);
        
        // Generate waveform for video's audio
        generateVideoWaveform(media).then(waveform => {
            audioClip.waveform = waveform;
            renderTimeline();
        });
    }
    
    clips.push(clip);
    updateDuration();
    renderTimeline();
    
    // Show preview
    if (media.type === 'video') {
        loadPreview(media.url);
    }
    
    toast('info', `Added "${media.name}" to timeline`);
}

async function generateVideoWaveform(media) {
    if (!ffmpegLoaded) return null;
    
    try {
        // Extract audio from video for waveform
        const inputName = 'input_wf' + media.file.name.substring(media.file.name.lastIndexOf('.'));
        ffmpeg.FS('writeFile', inputName, await window.ffmpegFetchFile(media.file));
        
        await ffmpeg.run('-i', inputName, '-ac', '1', '-ar', '8000', '-f', 'f32le', '-acodec', 'pcm_f32le', 'audio.raw');
        
        const audioData = ffmpeg.FS('readFile', 'audio.raw');
        const floatArray = new Float32Array(audioData.buffer);
        
        const samples = 200;
        const blockSize = Math.floor(floatArray.length / samples);
        const waveformData = [];
        
        for (let i = 0; i < samples; i++) {
            let sum = 0;
            for (let j = 0; j < blockSize; j++) {
                const idx = i * blockSize + j;
                if (idx < floatArray.length) {
                    sum += Math.abs(floatArray[idx]);
                }
            }
            waveformData.push(sum / blockSize);
        }
        
        const max = Math.max(...waveformData);
        
        ffmpeg.FS('unlink', inputName);
        ffmpeg.FS('unlink', 'audio.raw');
        
        return waveformData.map(v => max > 0 ? v / max : 0);
    } catch (e) {
        console.warn('Video waveform extraction failed:', e);
        return null;
    }
}

function renderTimeline() {
    const tracks = {
        video: document.getElementById('videoTrack'),
        audio: document.getElementById('audioTrack'),
        music: document.getElementById('musicTrack')
    };
    
    // Clear tracks
    Object.values(tracks).forEach(track => {
        track.innerHTML = '';
    });
    
    // Set timeline width based on duration
    const totalWidth = Math.max(duration * pixelsPerSecond + 500, document.getElementById('tracksContainer').offsetWidth);
    document.getElementById('tracksScroll').style.width = totalWidth + 'px';
    
    // Render clips
    clips.forEach(clip => {
        const track = tracks[clip.track];
        if (!track) return;
        
        const left = clip.startTime * pixelsPerSecond;
        const width = clip.duration * pixelsPerSecond;
        
        const clipEl = document.createElement('div');
        clipEl.className = `clip ${clip.track !== 'video' ? 'audio-clip' : ''} ${selectedClips.includes(clip) ? 'selected' : ''}`;
        clipEl.dataset.id = clip.id;
        clipEl.style.left = left + 'px';
        clipEl.style.width = width + 'px';
        
        if (clip.track === 'video') {
            clipEl.style.background = `var(--track-video)`;
        } else if (clip.track === 'audio') {
            clipEl.style.background = `var(--track-audio)`;
        } else {
            clipEl.style.background = `var(--track-music)`;
        }
        
        clipEl.innerHTML = `
            <div class="clip-header">${clip.name}</div>
            <div class="clip-content">
                ${clip.thumbnail && clip.type === 'video' ? `<img class="clip-thumbnail" src="${clip.thumbnail}">` : ''}
                ${clip.waveform ? `<canvas class="waveform-canvas" data-clip="${clip.id}"></canvas>` : ''}
            </div>
            <div class="clip-handle left"></div>
            <div class="clip-handle right"></div>
        `;
        
        track.appendChild(clipEl);
        
        // Draw waveform
        if (clip.waveform) {
            requestAnimationFrame(() => {
                const canvas = clipEl.querySelector('.waveform-canvas');
                if (canvas) {
                    drawWaveform(canvas, clip.waveform, clip.track);
                }
            });
        }
    });
    
    // Render transitions
    transitions.forEach(trans => {
        const track = tracks.video;
        const left = trans.time * pixelsPerSecond - trans.duration * pixelsPerSecond / 2;
        const width = trans.duration * pixelsPerSecond;
        
        const transEl = document.createElement('div');
        transEl.className = `transition ${selectedClips.some(c => c.transitionId === trans.id) ? 'selected' : ''}`;
        transEl.dataset.transitionId = trans.id;
        transEl.style.left = left + 'px';
        transEl.style.width = Math.max(width, 20) + 'px';
        transEl.innerHTML = '🔀';
        transEl.title = trans.type;
        
        track.appendChild(transEl);
    });
    
    // Update playhead
    updatePlayhead();
    renderRuler();
}

function drawWaveform(canvas, waveformData, track) {
    const ctx = canvas.getContext('2d');
    const width = canvas.offsetWidth;
    const height = canvas.offsetHeight;
    
    canvas.width = width;
    canvas.height = height;
    
    const color = track === 'video' || track === 'audio' ? '#22c55e' : '#06b6d4';
    
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.7;
    
    const barWidth = width / waveformData.length;
    const centerY = height / 2;
    
    for (let i = 0; i < waveformData.length; i++) {
        const barHeight = waveformData[i] * height * 0.8;
        const x = i * barWidth;
        ctx.fillRect(x, centerY - barHeight / 2, barWidth - 1, barHeight);
    }
}

function renderRuler() {
    const rulerEl = document.getElementById('rulerMarkers');
    const containerWidth = document.getElementById('tracksContainer').offsetWidth;
    const totalWidth = Math.max(duration * pixelsPerSecond + 500, containerWidth);
    
    rulerEl.innerHTML = '';
    
    // Determine interval based on zoom
    let interval = 1; // seconds
    if (pixelsPerSecond < 20) interval = 10;
    else if (pixelsPerSecond < 50) interval = 5;
    else if (pixelsPerSecond > 100) interval = 0.5;
    
    const numMarks = Math.ceil(totalWidth / (interval * pixelsPerSecond)) + 1;
    
    for (let i = 0; i <= numMarks; i++) {
        const time = i * interval;
        const x = time * pixelsPerSecond;
        
        const major = i % (interval < 1 ? 2 : 5) === 0;
        
        const mark = document.createElement('div');
        mark.className = `ruler-mark ${major ? 'major' : 'minor'}`;
        mark.style.left = x + 'px';
        rulerEl.appendChild(mark);
        
        if (major) {
            const label = document.createElement('div');
            label.className = 'ruler-label';
            label.style.left = x + 'px';
            label.textContent = formatTimecodeShort(time);
            rulerEl.appendChild(label);
        }
    }
}

// ==================== TIMELINE INTERACTIONS ====================
function onTimelineMouseDown(e) {
    const rect = document.getElementById('tracksContainer').getBoundingClientRect();
    const x = e.clientX - rect.left + document.getElementById('tracksContainer').scrollLeft;
    const y = e.clientY - rect.top;
    
    // Check for playhead
    const playheadX = currentTime * pixelsPerSecond;
    if (Math.abs(x - playheadX) < 10) {
        isDraggingPlayhead = true;
        return;
    }
    
    // Check for clip handle
    const handle = e.target.closest('.clip-handle');
    if (handle) {
        const clipEl = handle.closest('.clip');
        const clip = clips.find(c => c.id == clipEl.dataset.id);
        if (clip) {
            draggingHandle = {
                clip,
                side: handle.classList.contains('left') ? 'left' : 'right',
                startX: x,
                originalStart: clip.startTime,
                originalDuration: clip.duration,
                originalIn: clip.inPoint,
                originalOut: clip.outPoint
            };
        }
        return;
    }
    
    // Check for clip selection
    const clipEl = e.target.closest('.clip');
    if (clipEl) {
        const clip = clips.find(c => c.id == clipEl.dataset.id);
        if (clip) {
            // Razor tool
            if (currentTool === 'razor') {
                splitClipAt(clip, x / pixelsPerSecond);
                return;
            }
            
            // Selection
            if (!e.shiftKey && !selectedClips.includes(clip)) {
                selectedClips = [];
            }
            
            if (!selectedClips.includes(clip)) {
                selectedClips.push(clip);
                
                // Also select linked clip
                if (clip.linkedTo) {
                    const linked = clips.find(c => c.id === clip.linkedTo);
                    if (linked && !selectedClips.includes(linked)) {
                        selectedClips.push(linked);
                    }
                }
            }
            
            draggingClip = {
                clip,
                startX: x,
                startY: y,
                originalStart: clip.startTime
            };
            
            updateClipPropertiesPanel(clip);
            renderTimeline();
        }
        return;
    }
    
    // Check for transition selection
    const transEl = e.target.closest('.transition');
    if (transEl) {
        const trans = transitions.find(t => t.id == transEl.dataset.transitionId);
        if (trans) {
            toast('info', `Selected ${trans.type} transition`);
        }
        return;
    }
    
    // Clicked on empty space - deselect
    if (!e.shiftKey) {
        selectedClips = [];
        renderTimeline();
        clearClipPropertiesPanel();
    }
}

function onTimelineMouseMove(e) {
    const rect = document.getElementById('tracksContainer').getBoundingClientRect();
    const x = e.clientX - rect.left + document.getElementById('tracksContainer').scrollLeft;
    const y = e.clientY - rect.top;
    
    // Dragging playhead
    if (isDraggingPlayhead) {
        currentTime = Math.max(0, Math.min(duration, x / pixelsPerSecond));
        updatePlayhead();
        seekPreview(currentTime);
        return;
    }
    
    // Dragging handle (trimming)
    if (draggingHandle) {
        const delta = (x - draggingHandle.startX) / pixelsPerSecond;
        
        if (draggingHandle.side === 'left') {
            // Trim start
            const newStart = Math.max(0, draggingHandle.originalStart + delta);
            const newIn = Math.max(0, draggingHandle.originalIn + delta);
            const maxStart = draggingHandle.originalStart + draggingHandle.originalDuration - 0.1;
            
            draggingHandle.clip.startTime = Math.min(newStart, maxStart);
            draggingHandle.clip.inPoint = Math.min(newIn, draggingHandle.originalOut - 0.1);
            draggingHandle.clip.duration = draggingHandle.originalDuration - (draggingHandle.clip.startTime - draggingHandle.originalStart);
        } else {
            // Trim end
            const newDuration = Math.max(0.1, draggingHandle.originalDuration + delta);
            const media = mediaItems.find(m => m.id === draggingHandle.clip.mediaId);
            const maxDuration = media ? media.duration - draggingHandle.clip.inPoint : newDuration;
            
            draggingHandle.clip.duration = Math.min(newDuration, maxDuration);
            draggingHandle.clip.outPoint = draggingHandle.clip.inPoint + draggingHandle.clip.duration;
        }
        
        // Update linked clip
        if (draggingHandle.clip.linkedTo) {
            const linked = clips.find(c => c.id === draggingHandle.clip.linkedTo);
            if (linked) {
                linked.startTime = draggingHandle.clip.startTime;
                linked.duration = draggingHandle.clip.duration;
                linked.inPoint = draggingHandle.clip.inPoint;
                linked.outPoint = draggingHandle.clip.outPoint;
            }
        }
        
        updateDuration();
        renderTimeline();
        return;
    }
    
    // Dragging clip
    if (draggingClip) {
        const delta = (x - draggingClip.startX) / pixelsPerSecond;
        const newStart = Math.max(0, draggingClip.originalStart + delta);
        
        // Snap to other clips
        let snappedStart = newStart;
        const snapThreshold = 10 / pixelsPerSecond;
        
        clips.forEach(other => {
            if (other.id === draggingClip.clip.id || other.id === draggingClip.clip.linkedTo) return;
            
            // Snap to start
            if (Math.abs(newStart - other.startTime) < snapThreshold) {
                snappedStart = other.startTime;
            }
            // Snap to end
            if (Math.abs(newStart - (other.startTime + other.duration)) < snapThreshold) {
                snappedStart = other.startTime + other.duration;
            }
            // Snap clip end to other start
            if (Math.abs((newStart + draggingClip.clip.duration) - other.startTime) < snapThreshold) {
                snappedStart = other.startTime - draggingClip.clip.duration;
            }
        });
        
        // Snap to playhead
        if (Math.abs(newStart - currentTime) < snapThreshold) {
            snappedStart = currentTime;
        }
        if (Math.abs((newStart + draggingClip.clip.duration) - currentTime) < snapThreshold) {
            snappedStart = currentTime - draggingClip.clip.duration;
        }
        
        draggingClip.clip.startTime = snappedStart;
        
        // Move linked clip
        if (draggingClip.clip.linkedTo) {
            const linked = clips.find(c => c.id === draggingClip.clip.linkedTo);
            if (linked) {
                linked.startTime = snappedStart;
            }
        }
        
        updateDuration();
        renderTimeline();
    }
}

function onTimelineMouseUp() {
    isDraggingPlayhead = false;
    draggingClip = null;
    draggingHandle = null;
}

function onTimelineWheel(e) {
    if (e.ctrlKey) {
        // Zoom
        e.preventDefault();
        const delta = e.deltaY > 0 ? -5 : 5;
        const newZoom = Math.max(10, Math.min(200, pixelsPerSecond + delta));
        document.getElementById('zoomSlider').value = newZoom;
        setZoom(newZoom);
    }
}

function onRulerClick(e) {
    const rect = document.getElementById('rulerMarkers').getBoundingClientRect();
    const x = e.clientX - rect.left;
    currentTime = Math.max(0, Math.min(duration, x / pixelsPerSecond));
    updatePlayhead();
    seekPreview(currentTime);
}

function onContextMenu(e) {
    const clipEl = e.target.closest('.clip');
    if (clipEl || selectedClips.length > 0) {
        e.preventDefault();
        const menu = document.getElementById('contextMenu');
        menu.style.left = e.clientX + 'px';
        menu.style.top = e.clientY + 'px';
        menu.classList.add('visible');
    }
}

// ==================== MEDIA DRAG & DROP ====================
function onMediaDragStart(e) {
    const item = e.target.closest('.media-item');
    if (item) {
        e.dataTransfer.setData('mediaId', item.dataset.id);
    }
}

// ==================== TIMELINE TOOLS ====================
function setTool(tool) {
    currentTool = tool;
    document.querySelectorAll('.tool-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tool === tool);
    });
}

function setZoom(value) {
    pixelsPerSecond = parseInt(value);
    document.getElementById('zoomValue').textContent = value + '%';
    renderTimeline();
}

// ==================== CLIP OPERATIONS ====================
function splitClip() {
    if (selectedClips.length === 0) {
        // Split all clips at playhead
        const clipsAtPlayhead = clips.filter(c => 
            c.startTime < currentTime && c.startTime + c.duration > currentTime
        );
        clipsAtPlayhead.forEach(clip => splitClipAt(clip, currentTime));
    } else {
        selectedClips.forEach(clip => {
            if (clip.startTime < currentTime && clip.startTime + clip.duration > currentTime) {
                splitClipAt(clip, currentTime);
            }
        });
    }
}

function splitClipAt(clip, time) {
    if (time <= clip.startTime || time >= clip.startTime + clip.duration) return;
    
    const splitPoint = time - clip.startTime;
    
    // Create new clip for second half
    const newClip = {
        ...clip,
        id: Date.now() + Math.random(),
        startTime: time,
        duration: clip.duration - splitPoint,
        inPoint: clip.inPoint + splitPoint,
        linkedTo: null
    };
    
    // Adjust original clip
    clip.duration = splitPoint;
    clip.outPoint = clip.inPoint + splitPoint;
    
    // Handle linked clips
    if (clip.linkedTo) {
        const linked = clips.find(c => c.id === clip.linkedTo);
        if (linked) {
            const newLinked = {
                ...linked,
                id: Date.now() + Math.random() + 1,
                startTime: time,
                duration: newClip.duration,
                inPoint: newClip.inPoint,
                linkedTo: newClip.id
            };
            newClip.linkedTo = newLinked.id;
            clips.push(newLinked);
            
            linked.duration = splitPoint;
            linked.outPoint = linked.inPoint + splitPoint;
        }
    }
    
    clips.push(newClip);
    renderTimeline();
    toast('info', 'Clip split');
}

function deleteSelected() {
    if (selectedClips.length === 0) return;
    
    selectedClips.forEach(clip => {
        // Also delete linked clip
        if (clip.linkedTo) {
            clips = clips.filter(c => c.id !== clip.linkedTo);
        }
        clips = clips.filter(c => c.id !== clip.id);
    });
    
    selectedClips = [];
    updateDuration();
    renderTimeline();
    clearClipPropertiesPanel();
    toast('info', 'Deleted selected clips');
}

function copyClip() {
    if (selectedClips.length === 0) return;
    clipboard = selectedClips.map(clip => ({ ...clip }));
    toast('info', 'Copied to clipboard');
}

function cutClip() {
    copyClip();
    deleteSelected();
}

function pasteClip() {
    if (!clipboard || clipboard.length === 0) return;
    
    const pasteTime = currentTime;
    const newClips = [];
    
    clipboard.forEach((clipData, index) => {
        const newClip = {
            ...clipData,
            id: Date.now() + Math.random() + index,
            startTime: pasteTime + (clipData.startTime - clipboard[0].startTime),
            linkedTo: null
        };
        newClips.push(newClip);
    });
    
    // Re-link clips if there were linked pairs
    for (let i = 0; i < clipboard.length; i++) {
        const original = clipboard[i];
        if (original.linkedTo) {
            const linkedIndex = clipboard.findIndex(c => c.id === original.linkedTo);
            if (linkedIndex !== -1) {
                newClips[i].linkedTo = newClips[linkedIndex].id;
            }
        }
    }
    
    clips.push(...newClips);
    selectedClips = newClips;
    updateDuration();
    renderTimeline();
    toast('info', 'Pasted clips');
}

function selectAllClips() {
    selectedClips = [...clips];
    renderTimeline();
}

function addTransition() {
    // Add transition at cut point or between selected clips
    const videoClips = clips.filter(c => c.track === 'video').sort((a, b) => a.startTime - b.startTime);
    
    for (let i = 0; i < videoClips.length - 1; i++) {
        const current = videoClips[i];
        const next = videoClips[i + 1];
        const gap = next.startTime - (current.startTime + current.duration);
        
        // If clips are adjacent or overlapping
        if (Math.abs(gap) < 0.1) {
            const transTime = current.startTime + current.duration;
            
            // Check if transition already exists
            if (!transitions.some(t => Math.abs(t.time - transTime) < 0.1)) {
                transitions.push({
                    id: Date.now() + Math.random(),
                    time: transTime,
                    duration: 1, // 1 second dissolve
                    type: currentTransitionType
                });
                renderTimeline();
                toast('success', `Added ${currentTransitionType} transition`);
                return;
            }
        }
    }
    
    toast('info', 'Position clips adjacent to add transition');
}

function selectTransitionType(type) {
    currentTransitionType = type;
    document.querySelectorAll('.transition-item').forEach(item => {
        item.classList.toggle('selected', item.dataset.transition === type);
    });
}

function unlinkAudio() {
    selectedClips.forEach(clip => {
        if (clip.linkedTo) {
            const linked = clips.find(c => c.id === clip.linkedTo);
            if (linked) {
                linked.linkedTo = null;
            }
            clip.linkedTo = null;
        }
    });
    toast('info', 'Audio unlinked');
}

// ==================== PLAYBACK ====================
function togglePlay() {
    if (isPlaying) {
        pause();
    } else {
        play();
    }
}

function play() {
    if (clips.length === 0) return;
    
    isPlaying = true;
    document.getElementById('playBtn').innerHTML = '⏸';
    
    // Start video playback
    if (previewVideo.src) {
        previewVideo.currentTime = currentTime;
        previewVideo.play();
    }
    
    playbackInterval = setInterval(() => {
        currentTime += 1/30;
        if (currentTime >= duration) {
            pause();
            currentTime = 0;
        }
        updatePlayhead();
    }, 1000/30);
}

function pause() {
    isPlaying = false;
    document.getElementById('playBtn').innerHTML = '▶';
    
    if (previewVideo.src) {
        previewVideo.pause();
    }
    
    if (playbackInterval) {
        clearInterval(playbackInterval);
        playbackInterval = null;
    }
}

function goToStart() {
    currentTime = 0;
    updatePlayhead();
    seekPreview(currentTime);
}

function goToEnd() {
    currentTime = duration;
    updatePlayhead();
    seekPreview(currentTime);
}

function stepForward() {
    currentTime = Math.min(duration, currentTime + 1);
    updatePlayhead();
    seekPreview(currentTime);
}

function stepBackward() {
    currentTime = Math.max(0, currentTime - 1);
    updatePlayhead();
    seekPreview(currentTime);
}

function updatePlayhead() {
    const playhead = document.getElementById('playhead');
    playhead.style.left = (currentTime * pixelsPerSecond) + 'px';
    
    document.getElementById('currentTime').textContent = formatTimecode(currentTime);
    
    // Auto-scroll timeline
    const container = document.getElementById('tracksContainer');
    const playheadX = currentTime * pixelsPerSecond;
    const viewLeft = container.scrollLeft;
    const viewRight = viewLeft + container.offsetWidth - 100;
    
    if (playheadX > viewRight) {
        container.scrollLeft = playheadX - 100;
    } else if (playheadX < viewLeft) {
        container.scrollLeft = Math.max(0, playheadX - 100);
    }
}

function updateDuration() {
    if (clips.length === 0) {
        duration = 0;
    } else {
        duration = Math.max(...clips.map(c => c.startTime + c.duration));
    }
    document.getElementById('totalTime').textContent = formatTimecode(duration);
}

// ==================== PREVIEW ====================
function loadPreview(url) {
    previewVideo.src = url;
    previewVideo.style.display = 'block';
    document.getElementById('previewPlaceholder').style.display = 'none';
}

function seekPreview(time) {
    if (previewVideo.src) {
        previewVideo.currentTime = time;
    }
}

function onVideoTimeUpdate() {
    if (isPlaying) {
        currentTime = previewVideo.currentTime;
        updatePlayhead();
    }
}

function onVideoLoaded() {
    console.log('Video loaded:', previewVideo.duration);
}

function onVideoEnded() {
    pause();
}

function setVolume(value) {
    previewVideo.volume = value / 100;
}

function toggleMute() {
    previewVideo.muted = !previewVideo.muted;
    document.querySelector('.volume-btn').textContent = previewVideo.muted ? '🔇' : '🔊';
}

// ==================== CLIP PROPERTIES ====================
function updateClipPropertiesPanel(clip) {
    document.querySelector('#clipProperties .properties-section-title').textContent = clip.name;
    document.getElementById('clipPropertiesContent').innerHTML = `
        <div style="font-size: 11px; color: var(--text-2);">
            Duration: ${formatTimecode(clip.duration)}<br>
            Start: ${formatTimecode(clip.startTime)}<br>
            Type: ${clip.type}
        </div>
    `;
    
    // Update sliders
    document.getElementById('opacitySlider').value = clip.opacity;
    document.getElementById('opacityValue').textContent = clip.opacity + '%';
    document.getElementById('scaleSlider').value = clip.scale;
    document.getElementById('scaleValue').textContent = clip.scale + '%';
    document.getElementById('rotationSlider').value = clip.rotation;
    document.getElementById('rotationValue').textContent = clip.rotation + '°';
    document.getElementById('brightnessSlider').value = clip.brightness;
    document.getElementById('brightnessValue').textContent = clip.brightness;
    document.getElementById('contrastSlider').value = clip.contrast;
    document.getElementById('contrastValue').textContent = clip.contrast;
    document.getElementById('saturationSlider').value = clip.saturation;
    document.getElementById('saturationValue').textContent = clip.saturation;
}

function clearClipPropertiesPanel() {
    document.querySelector('#clipProperties .properties-section-title').textContent = 'No Clip Selected';
    document.getElementById('clipPropertiesContent').innerHTML = 'Select a clip on the timeline to view its properties';
}

function updateClipProperty(property, value) {
    const valueEl = document.getElementById(property + 'Value');
    if (valueEl) {
        valueEl.textContent = value + (property === 'rotation' ? '°' : '%');
    }
    
    selectedClips.forEach(clip => {
        clip[property] = parseInt(value);
    });
}

// ==================== EXPORT ====================
function showExportModal() {
    if (clips.length === 0) {
        toast('error', 'No clips to export');
        return;
    }
    document.getElementById('exportModal').classList.remove('hidden');
}

function hideExportModal() {
    document.getElementById('exportModal').classList.add('hidden');
}

async function exportVideo() {
    if (!ffmpegLoaded || clips.length === 0) return;
    
    hideExportModal();
    
    const overlay = document.getElementById('loadingOverlay');
    overlay.classList.remove('hidden');
    document.getElementById('loadingText').textContent = 'Exporting video...';
    document.getElementById('loadingProgress').style.width = '0%';
    
    try {
        const format = document.getElementById('exportFormat').value;
        const resolution = document.getElementById('exportResolution').value;
        const quality = document.getElementById('exportQuality').value;
        const filename = document.getElementById('exportFilename').value || 'export';
        
        // For now, export the first video clip
        // In a full implementation, this would composite all clips
        const videoClip = clips.find(c => c.type === 'video');
        if (!videoClip) {
            throw new Error('No video clips to export');
        }
        
        const media = mediaItems.find(m => m.id === videoClip.mediaId);
        if (!media) {
            throw new Error('Source media not found');
        }
        
        const inputName = 'input' + media.file.name.substring(media.file.name.lastIndexOf('.'));
        const outputName = `output.${format}`;
        
        ffmpeg.FS('writeFile', inputName, await window.ffmpegFetchFile(media.file));
        
        const args = ['-i', inputName];
        
        // Trim
        if (videoClip.inPoint > 0) {
            args.unshift('-ss', String(videoClip.inPoint));
        }
        args.push('-t', String(videoClip.duration));
        
        // Video filters
        const vf = [];
        if (resolution && resolution !== 'original') {
            const [w, h] = resolution.split(':');
            vf.push(`scale=${w}:${h}:force_original_aspect_ratio=decrease`);
        }
        if (videoClip.brightness || videoClip.contrast || videoClip.saturation) {
            const br = videoClip.brightness / 100;
            const ct = 1 + videoClip.contrast / 100;
            const st = 1 + videoClip.saturation / 100;
            vf.push(`eq=brightness=${br}:contrast=${ct}:saturation=${st}`);
        }
        if (videoClip.rotation) {
            vf.push(`rotate=${videoClip.rotation}*PI/180`);
        }
        
        if (vf.length > 0) {
            args.push('-vf', vf.join(','));
        }
        
        // Codec settings
        if (format === 'mp4') {
            args.push('-c:v', 'libx264', '-crf', quality, '-c:a', 'aac', '-b:a', '192k');
        } else if (format === 'webm') {
            args.push('-c:v', 'libvpx-vp9', '-crf', quality, '-b:v', '0', '-c:a', 'libopus');
        } else if (format === 'gif') {
            args.push('-vf', `fps=15,scale=480:-1:flags=lanczos`, '-loop', '0');
        }
        
        args.push('-y', outputName);
        
        await ffmpeg.run(...args);
        
        const data = ffmpeg.FS('readFile', outputName);
        const blob = new Blob([data.buffer], { type: format === 'gif' ? 'image/gif' : `video/${format}` });
        
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${filename}.${format}`;
        a.click();
        
        ffmpeg.FS('unlink', inputName);
        ffmpeg.FS('unlink', outputName);
        
        overlay.classList.add('hidden');
        toast('success', 'Video exported successfully!');
    } catch (e) {
        console.error('Export error:', e);
        overlay.classList.add('hidden');
        toast('error', 'Export failed: ' + e.message);
    }
}

// ==================== PROJECT MANAGEMENT ====================
function saveProject() {
    const project = {
        mediaItems: mediaItems.map(m => ({ ...m, file: null, url: null, thumbnail: m.type === 'image' ? m.thumbnail : null })),
        clips,
        transitions,
        duration
    };
    
    const json = JSON.stringify(project, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'project.clipforge';
    a.click();
    
    toast('success', 'Project saved');
}

function undo() {
    toast('info', 'Undo not yet implemented');
}

function showEditMenu(e) {
    // Could show a dropdown menu
}

// ==================== UTILITIES ====================
function formatTimecode(seconds) {
    if (!seconds || isNaN(seconds)) return '00:00:00:00';
    
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const f = Math.floor((seconds % 1) * 30);
    
    return [h, m, s, f].map(v => String(v).padStart(2, '0')).join(':');
}

function formatTimecodeShort(seconds) {
    if (!seconds || isNaN(seconds)) return '0:00';
    
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    
    return `${m}:${String(s).padStart(2, '0')}`;
}

function toast(type, message) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
        <span class="toast-text">${message}</span>
    `;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

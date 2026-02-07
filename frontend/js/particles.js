/**
 * Particle Flow Animation for Tidal Currents
 *
 * Windy-style particles that flow through the triangular mesh,
 * leaving fading trails colored by current speed.
 *
 * Two classes:
 *   TriangleSpatialIndex - Grid lookup for "which triangle contains point?"
 *   ParticleSystem       - Canvas2D overlay with trail-effect rendering
 */

const PARTICLE_DEBUG = false;

// ─── Triangle Spatial Index ──────────────────────────────────────────────────

class TriangleSpatialIndex {
    constructor(lats, lons, triangles, gridSize = 50) {
        this.lats = lats;
        this.lons = lons;
        this.triangles = triangles;
        this.gridSize = gridSize;

        this.minLat = Infinity;
        this.maxLat = -Infinity;
        this.minLon = Infinity;
        this.maxLon = -Infinity;
        for (let i = 0; i < lats.length; i++) {
            if (lats[i] < this.minLat) this.minLat = lats[i];
            if (lats[i] > this.maxLat) this.maxLat = lats[i];
            if (lons[i] < this.minLon) this.minLon = lons[i];
            if (lons[i] > this.maxLon) this.maxLon = lons[i];
        }

        this.latRange = this.maxLat - this.minLat || 1e-6;
        this.lonRange = this.maxLon - this.minLon || 1e-6;

        this.grid = new Array(gridSize * gridSize);
        for (let i = 0; i < this.grid.length; i++) this.grid[i] = [];
        this._buildIndex();
    }

    _buildIndex() {
        const { lats, lons, triangles, gridSize, minLat, minLon, latRange, lonRange } = this;
        for (let t = 0; t < triangles.length; t++) {
            const tri = triangles[t];
            const lat0 = lats[tri[0]], lat1 = lats[tri[1]], lat2 = lats[tri[2]];
            const lon0 = lons[tri[0]], lon1 = lons[tri[1]], lon2 = lons[tri[2]];

            const tMinLat = Math.min(lat0, lat1, lat2);
            const tMaxLat = Math.max(lat0, lat1, lat2);
            const tMinLon = Math.min(lon0, lon1, lon2);
            const tMaxLon = Math.max(lon0, lon1, lon2);

            const r0 = Math.max(0, Math.floor((tMinLat - minLat) / latRange * gridSize));
            const r1 = Math.min(gridSize - 1, Math.floor((tMaxLat - minLat) / latRange * gridSize));
            const c0 = Math.max(0, Math.floor((tMinLon - minLon) / lonRange * gridSize));
            const c1 = Math.min(gridSize - 1, Math.floor((tMaxLon - minLon) / lonRange * gridSize));

            for (let r = r0; r <= r1; r++) {
                for (let c = c0; c <= c1; c++) {
                    this.grid[r * gridSize + c].push(t);
                }
            }
        }
    }

    findTriangle(lat, lon) {
        const { gridSize, minLat, minLon, latRange, lonRange } = this;
        const r = Math.min(gridSize - 1, Math.max(0, Math.floor((lat - minLat) / latRange * gridSize)));
        const c = Math.min(gridSize - 1, Math.max(0, Math.floor((lon - minLon) / lonRange * gridSize)));

        const candidates = this.grid[r * gridSize + c];
        for (let i = 0; i < candidates.length; i++) {
            if (this._pointInTriangle(lat, lon, candidates[i])) return candidates[i];
        }
        return -1;
    }

    getBarycentricCoords(lat, lon, tIdx) {
        const tri = this.triangles[tIdx];
        const ax = this.lons[tri[0]], ay = this.lats[tri[0]];
        const bx = this.lons[tri[1]], by = this.lats[tri[1]];
        const cx = this.lons[tri[2]], cy = this.lats[tri[2]];

        const v0x = cx - ax, v0y = cy - ay;
        const v1x = bx - ax, v1y = by - ay;
        const v2x = lon - ax, v2y = lat - ay;

        const dot00 = v0x * v0x + v0y * v0y;
        const dot01 = v0x * v1x + v0y * v1y;
        const dot02 = v0x * v2x + v0y * v2y;
        const dot11 = v1x * v1x + v1y * v1y;
        const dot12 = v1x * v2x + v1y * v2y;

        const inv = 1 / (dot00 * dot11 - dot01 * dot01);
        const u = (dot11 * dot02 - dot01 * dot12) * inv;
        const v = (dot00 * dot12 - dot01 * dot02) * inv;
        return [1 - u - v, v, u];
    }

    _pointInTriangle(lat, lon, tIdx) {
        const tri = this.triangles[tIdx];
        const ax = this.lons[tri[0]], ay = this.lats[tri[0]];
        const bx = this.lons[tri[1]], by = this.lats[tri[1]];
        const cx = this.lons[tri[2]], cy = this.lats[tri[2]];

        const v0x = cx - ax, v0y = cy - ay;
        const v1x = bx - ax, v1y = by - ay;
        const v2x = lon - ax, v2y = lat - ay;

        const dot00 = v0x * v0x + v0y * v0y;
        const dot01 = v0x * v1x + v0y * v1y;
        const dot02 = v0x * v2x + v0y * v2y;
        const dot11 = v1x * v1x + v1y * v1y;
        const dot12 = v1x * v2x + v1y * v2y;

        const inv = 1 / (dot00 * dot11 - dot01 * dot01);
        const u = (dot11 * dot02 - dot01 * dot12) * inv;
        const v = (dot00 * dot12 - dot01 * dot02) * inv;
        return u >= -1e-6 && v >= -1e-6 && (u + v) <= 1 + 1e-6;
    }
}

// ─── Particle System ─────────────────────────────────────────────────────────

class ParticleSystem {
    constructor(map, meshData, opts = {}) {
        this.map = map;
        this.numParticles = opts.numParticles || 5000;
        this.speedScale = opts.speedScale || 0.5;
        this.maxAge = opts.maxAge || 100;
        this.trailFade = opts.trailFade || 0.96;
        this.lineWidth = opts.lineWidth || 1.5;

        this._frameSkip = opts.frameSkip || 1;
        this._frameCounter = 0;
        this._running = false;
        this._animId = null;
        this._isMoving = false;
        this._particles = [];
        this._renderFrameCount = 0;

        // Speed-based color palette (blue → cyan → green → yellow → red)
        this._colorStops = [
            { speed: 0.00, r: 50,  g: 80,  b: 200 },
            { speed: 0.10, r: 40,  g: 120, b: 230 },
            { speed: 0.20, r: 0,   g: 180, b: 240 },
            { speed: 0.30, r: 0,   g: 220, b: 180 },
            { speed: 0.40, r: 0,   g: 240, b: 120 },
            { speed: 0.50, r: 100, g: 240, b: 60  },
            { speed: 0.60, r: 180, g: 240, b: 0   },
            { speed: 0.70, r: 240, g: 220, b: 0   },
            { speed: 0.85, r: 255, g: 160, b: 0   },
            { speed: 1.00, r: 255, g: 100, b: 0   },
            { speed: 1.25, r: 255, g: 40,  b: 40  },
            { speed: 1.50, r: 200, g: 0,   b: 60  },
        ];

        try {
            this._buildFromMeshData(meshData);
            this._createCanvas();

            this._onMove = () => { this._isMoving = true; };
            this._onMoveEnd = () => {
                this._isMoving = false;
                if (this._ctx) {
                    this._ctx.clearRect(0, 0, this._canvas.clientWidth, this._canvas.clientHeight);
                }
            };
            this._onResize = () => { this._syncCanvasSize(); };

            map.on('move', this._onMove);
            map.on('moveend', this._onMoveEnd);
            map.on('resize', this._onResize);
            window.addEventListener('resize', this._onResize);

            if (PARTICLE_DEBUG) console.log('ParticleSystem: initialized successfully');
        } catch (e) {
            console.error('ParticleSystem: initialization failed:', e);
        }
    }

    // ─── Data ────────────────────────────────────────────────────────

    _buildFromMeshData(meshData) {
        const { lat, lon, u_velocity, v_velocity } = meshData.nodes;
        this._lats = lat;
        this._lons = lon;
        this._u = u_velocity;
        this._v = v_velocity;

        // Pre-compute speed at each node for coloring
        this._speed = new Float64Array(lat.length);
        for (let i = 0; i < lat.length; i++) {
            this._speed[i] = Math.sqrt(u_velocity[i] * u_velocity[i] + v_velocity[i] * v_velocity[i]);
        }

        if (PARTICLE_DEBUG) {
            let minSpeed = Infinity, maxSpeed = -Infinity;
            for (let i = 0; i < lat.length; i++) {
                if (this._speed[i] < minSpeed) minSpeed = this._speed[i];
                if (this._speed[i] > maxSpeed) maxSpeed = this._speed[i];
            }
            console.log(`[ParticleData] ${lat.length} nodes, speed range: [${minSpeed.toFixed(6)}, ${maxSpeed.toFixed(6)}]`);
        }

        if (meshData.elements && meshData.elements.triangles && meshData.elements.triangles.length > 0) {
            this._spatialIndex = new TriangleSpatialIndex(lat, lon, meshData.elements.triangles);
            this._triangles = meshData.elements.triangles;
        } else {
            this._spatialIndex = null;
            this._triangles = null;
        }

        this._dataMinLat = Infinity;
        this._dataMaxLat = -Infinity;
        this._dataMinLon = Infinity;
        this._dataMaxLon = -Infinity;
        for (let i = 0; i < lat.length; i++) {
            if (lat[i] < this._dataMinLat) this._dataMinLat = lat[i];
            if (lat[i] > this._dataMaxLat) this._dataMaxLat = lat[i];
            if (lon[i] < this._dataMinLon) this._dataMinLon = lon[i];
            if (lon[i] > this._dataMaxLon) this._dataMaxLon = lon[i];
        }
    }

    // ─── Canvas ──────────────────────────────────────────────────────

    _createCanvas() {
        this._canvas = document.createElement('canvas');
        this._canvas.style.position = 'absolute';
        this._canvas.style.top = '0';
        this._canvas.style.left = '0';
        this._canvas.style.pointerEvents = 'none';
        this._canvas.style.zIndex = '10';
        this._ctx = this._canvas.getContext('2d');
        this.map.getCanvasContainer().appendChild(this._canvas);
        this._syncCanvasSize();
    }

    _syncCanvasSize() {
        const dpr = window.devicePixelRatio || 1;
        const mapContainer = this.map.getContainer();
        const w = mapContainer.clientWidth;
        const h = mapContainer.clientHeight;

        this._canvas.width = w * dpr;
        this._canvas.height = h * dpr;
        this._canvas.style.width = w + 'px';
        this._canvas.style.height = h + 'px';
        this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    // ─── Particles ───────────────────────────────────────────────────

    _spawnParticle() {
        const bounds = this.map.getBounds();
        const minLat = Math.max(bounds.getSouth(), this._dataMinLat);
        const maxLat = Math.min(bounds.getNorth(), this._dataMaxLat);
        const minLon = Math.max(bounds.getWest(), this._dataMinLon);
        const maxLon = Math.min(bounds.getEast(), this._dataMaxLon);

        return {
            lat: minLat + Math.random() * (maxLat - minLat),
            lon: minLon + Math.random() * (maxLon - minLon),
            prevLat: NaN,
            prevLon: NaN,
            age: Math.floor(Math.random() * this.maxAge),
            speed: 0
        };
    }

    _resetParticle(p) {
        const bounds = this.map.getBounds();
        const minLat = Math.max(bounds.getSouth(), this._dataMinLat);
        const maxLat = Math.min(bounds.getNorth(), this._dataMaxLat);
        const minLon = Math.max(bounds.getWest(), this._dataMinLon);
        const maxLon = Math.min(bounds.getEast(), this._dataMaxLon);

        p.lat = minLat + Math.random() * (maxLat - minLat);
        p.lon = minLon + Math.random() * (maxLon - minLon);
        p.prevLat = NaN;
        p.prevLon = NaN;
        p.age = 0;
        p.speed = 0;
    }

    _initParticles() {
        this._particles = [];
        for (let i = 0; i < this.numParticles; i++) {
            this._particles.push(this._spawnParticle());
        }

        if (PARTICLE_DEBUG) {
            console.log(`[ParticleInit] Spawned ${this._particles.length} particles`);
        }
    }

    // ─── Color ───────────────────────────────────────────────────────

    _speedToColor(speed) {
        const stops = this._colorStops;
        if (speed <= stops[0].speed) {
            return `rgb(${stops[0].r},${stops[0].g},${stops[0].b})`;
        }
        for (let i = 1; i < stops.length; i++) {
            if (speed <= stops[i].speed) {
                const t = (speed - stops[i-1].speed) / (stops[i].speed - stops[i-1].speed);
                const r = Math.round(stops[i-1].r + t * (stops[i].r - stops[i-1].r));
                const g = Math.round(stops[i-1].g + t * (stops[i].g - stops[i-1].g));
                const b = Math.round(stops[i-1].b + t * (stops[i].b - stops[i-1].b));
                return `rgb(${r},${g},${b})`;
            }
        }
        const last = stops[stops.length - 1];
        return `rgb(${last.r},${last.g},${last.b})`;
    }

    _getColorBucket(speed) {
        if (speed < 0.10) return 0;
        if (speed < 0.20) return 1;
        if (speed < 0.30) return 2;
        if (speed < 0.40) return 3;
        if (speed < 0.50) return 4;
        if (speed < 0.60) return 5;
        if (speed < 0.75) return 6;
        if (speed < 1.00) return 7;
        if (speed < 1.25) return 8;
        return 9;
    }

    // ─── Public API ──────────────────────────────────────────────────

    start() {
        if (this._running) return;
        this._running = true;
        this._initParticles();
        console.log(`ParticleSystem: started (${this.numParticles} particles, ` +
            `${this._triangles ? this._triangles.length : 0} triangles)`);
        this._animate();
    }

    stop() {
        this._running = false;
        if (this._animId) {
            cancelAnimationFrame(this._animId);
            this._animId = null;
        }
        if (this._ctx) {
            this._ctx.clearRect(0, 0, this._canvas.clientWidth, this._canvas.clientHeight);
        }
    }

    toggle() {
        if (this._running) { this.stop(); return false; }
        else { this.start(); return true; }
    }

    isRunning() { return this._running; }

    destroy() {
        this.stop();
        this.map.off('move', this._onMove);
        this.map.off('moveend', this._onMoveEnd);
        this.map.off('resize', this._onResize);
        window.removeEventListener('resize', this._onResize);
        if (this._canvas && this._canvas.parentNode) {
            this._canvas.parentNode.removeChild(this._canvas);
        }
        this._canvas = null;
        this._ctx = null;
    }

    updateMeshData(meshData) {
        this._buildFromMeshData(meshData);
        if (this._running) {
            this._initParticles();
            if (this._ctx) {
                this._ctx.clearRect(0, 0, this._canvas.clientWidth, this._canvas.clientHeight);
            }
        }
    }

    // ─── Animation Loop ──────────────────────────────────────────────

    _animate() {
        if (!this._running) return;
        this._frameCounter++;
        this._update();
        // Skip rendering on alternate frames for low-end devices
        if (this._frameCounter % this._frameSkip === 0) {
            this._render();
        }
        this._animId = requestAnimationFrame(() => this._animate());
    }

    _update() {
        const hasSpatialIndex = !!this._spatialIndex;

        const bounds = this.map.getBounds();
        const mapArea = Math.abs(
            (bounds.getNorth() - bounds.getSouth()) *
            (bounds.getEast() - bounds.getWest())
        );
        const adaptiveScale = this.speedScale * Math.pow(mapArea, 0.4);

        for (let i = 0; i < this._particles.length; i++) {
            const p = this._particles[i];
            p.age++;

            if (p.age >= this.maxAge) {
                this._resetParticle(p);
                continue;
            }

            let u = 0, v = 0, speed = 0;

            if (hasSpatialIndex) {
                const tIdx = this._spatialIndex.findTriangle(p.lat, p.lon);
                if (tIdx < 0) {
                    this._resetParticle(p);
                    continue;
                }

                const [w0, w1, w2] = this._spatialIndex.getBarycentricCoords(p.lat, p.lon, tIdx);
                const tri = this._triangles[tIdx];
                u = w0 * this._u[tri[0]] + w1 * this._u[tri[1]] + w2 * this._u[tri[2]];
                v = w0 * this._v[tri[0]] + w1 * this._v[tri[1]] + w2 * this._v[tri[2]];
                speed = w0 * this._speed[tri[0]] + w1 * this._speed[tri[1]] + w2 * this._speed[tri[2]];
            } else {
                const nearest = this._findNearestNode(p.lat, p.lon);
                if (nearest >= 0) {
                    u = this._u[nearest];
                    v = this._v[nearest];
                    speed = this._speed[nearest];
                }
            }

            p.speed = speed;
            p.prevLat = p.lat;
            p.prevLon = p.lon;

            const px = this.map.project([p.lon, p.lat]);
            px.x += u * adaptiveScale;
            px.y -= v * adaptiveScale;

            const newPos = this.map.unproject(px);
            p.lat = newPos.lat;
            p.lon = newPos.lng;
        }
    }

    _findNearestNode(lat, lon) {
        let minDist = Infinity;
        let nearest = -1;
        const limit = Math.min(this._lats.length, 2000);
        for (let i = 0; i < limit; i++) {
            const dlat = this._lats[i] - lat;
            const dlon = this._lons[i] - lon;
            const d = dlat * dlat + dlon * dlon;
            if (d < minDist) { minDist = d; nearest = i; }
        }
        return nearest;
    }

    _render() {
        const ctx = this._ctx;
        if (!ctx) return;

        const w = this._canvas.clientWidth;
        const h = this._canvas.clientHeight;

        this._renderFrameCount++;

        if (this._isMoving) {
            ctx.clearRect(0, 0, w, h);
            return;
        }

        // Trail fade: multiply all existing pixel alpha by trailFade
        ctx.globalCompositeOperation = 'destination-in';
        ctx.fillStyle = `rgba(0, 0, 0, ${this.trailFade})`;
        ctx.fillRect(0, 0, w, h);
        ctx.globalCompositeOperation = 'source-over';

        // Draw particles grouped by color bucket for efficient batched strokes
        const bucketColors = [
            'rgba(50, 80, 200, 0.75)',
            'rgba(40, 120, 230, 0.8)',
            'rgba(0, 180, 240, 0.85)',
            'rgba(0, 220, 180, 0.85)',
            'rgba(0, 240, 120, 0.9)',
            'rgba(100, 240, 60, 0.9)',
            'rgba(180, 240, 0, 0.9)',
            'rgba(240, 220, 0, 0.95)',
            'rgba(255, 160, 0, 0.95)',
            'rgba(255, 40, 40, 0.95)',
        ];

        ctx.lineWidth = this.lineWidth;
        ctx.lineCap = 'round';

        for (let b = 0; b < bucketColors.length; b++) {
            ctx.strokeStyle = bucketColors[b];
            ctx.beginPath();
            let hasSegments = false;

            for (let i = 0; i < this._particles.length; i++) {
                const p = this._particles[i];
                if (isNaN(p.prevLat)) continue;
                if (this._getColorBucket(p.speed) !== b) continue;

                const prev = this.map.project([p.prevLon, p.prevLat]);
                const curr = this.map.project([p.lon, p.lat]);

                if (prev.x < -50 || prev.x > w + 50 || prev.y < -50 || prev.y > h + 50) continue;

                ctx.moveTo(prev.x, prev.y);
                ctx.lineTo(curr.x, curr.y);
                hasSegments = true;
            }

            if (hasSegments) ctx.stroke();
        }
    }
}

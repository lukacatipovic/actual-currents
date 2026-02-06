/**
 * Particle Flow Animation System for Tidal Currents
 *
 * Two classes:
 *   TriangleSpatialIndex - Grid-based lookup for "which triangle contains point?"
 *   ParticleSystem       - Canvas2D overlay with trail-effect rendering
 */

// ─── Triangle Spatial Index ──────────────────────────────────────────────────

class TriangleSpatialIndex {
    /**
     * @param {number[]} lats   - Node latitudes
     * @param {number[]} lons   - Node longitudes
     * @param {number[][]} triangles - Each element is [i0, i1, i2] node indices
     * @param {number} gridSize - Grid resolution (default 50)
     */
    constructor(lats, lons, triangles, gridSize = 50) {
        this.lats = lats;
        this.lons = lons;
        this.triangles = triangles;
        this.gridSize = gridSize;

        // Compute bounding box of all nodes
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

        // Build the grid
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

            // Triangle bounding box
            const tMinLat = Math.min(lat0, lat1, lat2);
            const tMaxLat = Math.max(lat0, lat1, lat2);
            const tMinLon = Math.min(lon0, lon1, lon2);
            const tMaxLon = Math.max(lon0, lon1, lon2);

            // Grid cell range
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

    /**
     * Find the triangle index containing the given point, or -1.
     */
    findTriangle(lat, lon) {
        const { gridSize, minLat, minLon, latRange, lonRange } = this;

        const r = Math.floor((lat - minLat) / latRange * gridSize);
        const c = Math.floor((lon - minLon) / lonRange * gridSize);

        if (r < 0 || r >= gridSize || c < 0 || c >= gridSize) return -1;

        const candidates = this.grid[r * gridSize + c];
        for (let i = 0; i < candidates.length; i++) {
            const tIdx = candidates[i];
            if (this._pointInTriangle(lat, lon, tIdx)) return tIdx;
        }
        return -1;
    }

    /**
     * Barycentric coordinates of point (lat, lon) inside triangle tIdx.
     * Returns [w0, w1, w2] where w0+w1+w2 ≈ 1.
     */
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

        return [1 - u - v, v, u]; // w0, w1, w2
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

        return u >= 0 && v >= 0 && (u + v) <= 1;
    }
}

// ─── Particle System ─────────────────────────────────────────────────────────

class ParticleSystem {
    /**
     * @param {mapboxgl.Map} map
     * @param {object} meshData - API response { nodes: {lat,lon,u_velocity,v_velocity}, elements: {triangles} }
     * @param {object} opts
     */
    constructor(map, meshData, opts = {}) {
        this.map = map;
        this.numParticles = opts.numParticles || 5000;
        this.speedScale = opts.speedScale || 3000;
        this.maxAge = opts.maxAge || 100;
        this.trailFade = opts.trailFade || 0.96;
        this.lineWidth = opts.lineWidth || 1.2;
        this.color = opts.color || 'rgba(255, 255, 255, 0.8)';

        this._running = false;
        this._animId = null;
        this._isMoving = false;
        this._particles = [];

        // Build spatial index
        this._buildFromMeshData(meshData);

        // Create canvas overlay
        this._createCanvas();

        // Event listeners (bound so we can remove them later)
        this._onMove = () => { this._isMoving = true; };
        this._onMoveEnd = () => { this._isMoving = false; };
        this._onResize = () => { this._syncCanvasSize(); };

        map.on('move', this._onMove);
        map.on('moveend', this._onMoveEnd);
        map.on('resize', this._onResize);
        window.addEventListener('resize', this._onResize);
    }

    _buildFromMeshData(meshData) {
        const { lat, lon, u_velocity, v_velocity } = meshData.nodes;
        this._lats = lat;
        this._lons = lon;
        this._u = u_velocity;
        this._v = v_velocity;

        // Need triangles for spatial index
        if (meshData.elements && meshData.elements.triangles && meshData.elements.triangles.length > 0) {
            this._spatialIndex = new TriangleSpatialIndex(lat, lon, meshData.elements.triangles);
            this._triangles = meshData.elements.triangles;
        } else {
            this._spatialIndex = null;
            this._triangles = null;
        }

        // Compute bounds for particle spawning
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

    _createCanvas() {
        this._canvas = document.createElement('canvas');
        this._canvas.style.position = 'absolute';
        this._canvas.style.top = '0';
        this._canvas.style.left = '0';
        this._canvas.style.pointerEvents = 'none';
        this._canvas.style.zIndex = '1';
        this._ctx = this._canvas.getContext('2d');

        this.map.getCanvasContainer().appendChild(this._canvas);
        this._syncCanvasSize();
    }

    _syncCanvasSize() {
        const container = this.map.getCanvasContainer();
        const dpr = window.devicePixelRatio || 1;
        const w = container.clientWidth;
        const h = container.clientHeight;

        this._canvas.width = w * dpr;
        this._canvas.height = h * dpr;
        this._canvas.style.width = w + 'px';
        this._canvas.style.height = h + 'px';
        this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    _spawnParticle() {
        // Spawn within viewport bounds, clamped to data extent
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
            age: Math.floor(Math.random() * this.maxAge) // stagger ages
        };
    }

    _initParticles() {
        this._particles = [];
        for (let i = 0; i < this.numParticles; i++) {
            this._particles.push(this._spawnParticle());
        }
    }

    // ─── Public API ───────────────────────────────────────────────────

    start() {
        if (this._running) return;
        this._running = true;
        this._initParticles();
        console.log(`ParticleSystem started: ${this.numParticles} particles, ` +
            `spatialIndex: ${!!this._spatialIndex}, ` +
            `triangles: ${this._triangles ? this._triangles.length : 0}, ` +
            `nodes: ${this._lats.length}, ` +
            `canvas: ${this._canvas.width}x${this._canvas.height}`);
        this._animate();
    }

    stop() {
        this._running = false;
        if (this._animId) {
            cancelAnimationFrame(this._animId);
            this._animId = null;
        }
        // Clear canvas
        const w = this._canvas.width;
        const h = this._canvas.height;
        this._ctx.clearRect(0, 0, w, h);
    }

    toggle() {
        if (this._running) {
            this.stop();
            return false;
        } else {
            this.start();
            return true;
        }
    }

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
        // Respawn particles to match new data area
        if (this._running) {
            this._initParticles();
        }
    }

    // ─── Animation Loop ──────────────────────────────────────────────

    _animate() {
        if (!this._running) return;
        this._update();
        this._render();
        this._frameCount = (this._frameCount || 0) + 1;
        if (this._frameCount <= 3 || this._frameCount % 300 === 0) {
            let insideMesh = 0;
            for (const p of this._particles) {
                if (!isNaN(p.prevLat)) insideMesh++;
            }
            console.log(`Particles frame ${this._frameCount}: ${insideMesh}/${this._particles.length} drawing, isMoving: ${this._isMoving}`);
        }
        this._animId = requestAnimationFrame(() => this._animate());
    }

    _update() {
        const dt = 1 / 60; // fixed timestep
        const hasSpatialIndex = !!this._spatialIndex;

        for (let i = 0; i < this._particles.length; i++) {
            const p = this._particles[i];
            p.age++;

            // Respawn if too old
            if (p.age >= this.maxAge) {
                const fresh = this._spawnParticle();
                p.lat = fresh.lat;
                p.lon = fresh.lon;
                p.prevLat = NaN;
                p.prevLon = NaN;
                p.age = 0;
                continue;
            }

            let u = 0, v = 0;

            if (hasSpatialIndex) {
                // Use spatial index + barycentric interpolation
                const tIdx = this._spatialIndex.findTriangle(p.lat, p.lon);
                if (tIdx < 0) {
                    // Outside mesh — respawn
                    const fresh = this._spawnParticle();
                    p.lat = fresh.lat;
                    p.lon = fresh.lon;
                    p.prevLat = NaN;
                    p.prevLon = NaN;
                    p.age = 0;
                    continue;
                }

                const [w0, w1, w2] = this._spatialIndex.getBarycentricCoords(p.lat, p.lon, tIdx);
                const tri = this._triangles[tIdx];
                u = w0 * this._u[tri[0]] + w1 * this._u[tri[1]] + w2 * this._u[tri[2]];
                v = w0 * this._v[tri[0]] + w1 * this._v[tri[1]] + w2 * this._v[tri[2]];
            } else {
                // Fallback: nearest-node interpolation
                u = this._nearestVelocity(p.lat, p.lon, 'u');
                v = this._nearestVelocity(p.lat, p.lon, 'v');
            }

            // Save previous position for trail drawing
            p.prevLat = p.lat;
            p.prevLon = p.lon;

            // Update position (velocity in m/s → degrees)
            // 1 degree latitude ≈ 111,000 m
            const cosLat = Math.cos(p.lat * Math.PI / 180);
            p.lat += v * dt * this.speedScale / 111000;
            p.lon += u * dt * this.speedScale / (111000 * cosLat);
        }
    }

    _nearestVelocity(lat, lon, component) {
        // Simple nearest-node fallback when no triangles available
        let minDist = Infinity;
        let nearest = 0;
        const arr = component === 'u' ? this._u : this._v;

        // Only check a subset for performance (first 1000 nodes)
        const limit = Math.min(this._lats.length, 1000);
        for (let i = 0; i < limit; i++) {
            const dlat = this._lats[i] - lat;
            const dlon = this._lons[i] - lon;
            const d = dlat * dlat + dlon * dlon;
            if (d < minDist) {
                minDist = d;
                nearest = i;
            }
        }
        return arr[nearest];
    }

    _render() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;

        if (this._isMoving) {
            // During map pan/zoom: clear everything (trails would be misaligned)
            ctx.clearRect(0, 0, w, h);
            return;
        }

        // Trail fade effect: draw semi-transparent fill over existing content
        ctx.globalCompositeOperation = 'destination-in';
        ctx.fillStyle = `rgba(0, 0, 0, ${this.trailFade})`;
        ctx.fillRect(0, 0, w, h);
        ctx.globalCompositeOperation = 'source-over';

        // Draw all particle trail segments in one batch
        ctx.strokeStyle = this.color;
        ctx.lineWidth = this.lineWidth;
        ctx.beginPath();

        for (let i = 0; i < this._particles.length; i++) {
            const p = this._particles[i];
            if (isNaN(p.prevLat)) continue;

            const prev = this.map.project([p.prevLon, p.prevLat]);
            const curr = this.map.project([p.lon, p.lat]);

            // Skip if off-screen
            if (prev.x < -50 || prev.x > w + 50 || prev.y < -50 || prev.y > h + 50) continue;

            ctx.moveTo(prev.x, prev.y);
            ctx.lineTo(curr.x, curr.y);
        }

        ctx.stroke();
    }
}

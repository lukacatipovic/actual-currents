// Global variables
let map;
let velocityLayer = null;
let currentZoom = 15;
let isUpdatingFromZoom = false;
let currentBasemap = 'dark';
let basemapLayers = {};
let currentsEnabled = true;
let particlesEnabled = true;

// Basemap configurations
const basemaps = {
    'osm': {
        name: 'OpenStreetMap',
        description: 'Standard street map',
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '© OpenStreetMap contributors',
        previewColor: '#4ade80',
        thumbnail: './images/osm.png' // Relative path from HTML file
    },
    'dark': {
        name: 'Dark Mode',
        description: 'Dark theme for night viewing',
        url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
        attribution: '© CARTO',
        previewColor: '#1e293b',
        thumbnail: 'images/dark.png' // Relative path
    },
    'satellite': {
        name: 'Satellite',
        description: 'Aerial imagery',
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attribution: '© Esri',
        previewColor: '#10b981',
        thumbnail: 'images/sat.png' // Relative path
    },
    'topo': {
        name: 'Topographic',
        description: 'Terrain and elevation',
        url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attribution: '© OpenTopoMap',
        previewColor: '#f59e0b',
        thumbnail: 'images/topo.png' // Relative path
    }
};

/// Initialize the application when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Tidal Currents Visualizer starting...');
    
    // Set time input to current EST time
    const timeInput = document.getElementById('timeInput');
    if (timeInput) {
        timeInput.value = getCurrentESTTime();
        console.log(`🕒 Set initial time to: ${timeInput.value} EST/EDT`);
    }
    
    initializeMap();
    initializeBasemapControls();
    initializeViewInfoUpdater();
    
    // Load initial data
    setTimeout(() => {
        loadCurrentData();
    }, 1000);
});

function getCurrentESTTime() {
    const now = new Date();
    
    // Create a date string in EST timezone
    // Using toLocaleString with timezone option
    const estTimeString = now.toLocaleString('en-US', {
        timeZone: 'America/New_York',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
    
    // Parse the string: "MM/DD/YYYY, HH:MM"
    const [datePart, timePart] = estTimeString.split(', ');
    const [month, day, year] = datePart.split('/');
    const [hours, minutes] = timePart.split(':');
    
    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

// Initialize Leaflet map
function initializeMap() {
    // Create map centered on Woods Hole
    map = L.map('map', {
        zoomControl: true,
        attributionControl: true,
        preferCanvas: true
    }).setView([41.52, -70.68], 14);
    
    // Add default basemap
    basemapLayers.dark = L.tileLayer(basemaps.dark.url, {
        attribution: basemaps.dark.attribution,
        maxZoom: 18
    }).addTo(map);
    
    // Add other basemaps (not added to map initially)
    for (const [key, config] of Object.entries(basemaps)) {
        if (key !== 'dark') {
            basemapLayers[key] = L.tileLayer(config.url, {
                attribution: config.attribution,
                maxZoom: 18
            });
        }
    }
    
    // Add scale control with custom styling
    L.control.scale({
        imperial: false,
        metric: true,
        position: 'bottomleft'
    }).addTo(map);
    
    // Customize attribution control
    map.attributionControl.setPrefix('<a href="https://leafletjs.com" title="A JS library for interactive maps">Leaflet</a>');
    
    // Track zoom changes
    map.on('zoomend', function() {
        const newZoom = map.getZoom();
        if (newZoom !== currentZoom) {
            currentZoom = newZoom;
            updateZoomDisplay();
            console.log(`🔍 Zoom changed to: ${currentZoom}`);
            
            if (!isUpdatingFromZoom) {
                clearTimeout(window.zoomTimeout);
                window.zoomTimeout = setTimeout(() => {
                    console.log(`🔄 Reloading data for zoom ${currentZoom}`);
                    loadCurrentData();
                }, 500);
            }
        }
    });
    
    // Track view changes (panning)
    map.on('moveend', function() {
        if (!isUpdatingFromZoom) {
            clearTimeout(window.moveTimeout);
            window.moveTimeout = setTimeout(() => {
                console.log('🔄 Reloading data for new view');
                loadCurrentData();
            }, 1000);
        }
    });
    
    console.log('✅ Map initialized with dark theme');
}

// Initialize basemap control buttons
function initializeBasemapControls() {
    const basemapContainer = document.getElementById('basemapControls');
    
    for (const [key, config] of Object.entries(basemaps)) {
        const basemapOption = document.createElement('div');
        basemapOption.className = `basemap-option ${key === currentBasemap ? 'active' : ''}`;
        basemapOption.onclick = () => switchBasemap(key);
        
        // Use the thumbnail image in the preview
        basemapOption.innerHTML = `
            <div class="basemap-preview">
                <img src="${config.thumbnail}" alt="${config.name}" class="basemap-thumbnail">
            </div>
            <div class="basemap-info">
                <div class="basemap-name">${config.name}</div>
                <div class="basemap-desc">${config.description}</div>
            </div>
        `;
        
        basemapContainer.appendChild(basemapOption);
    }
}

// Switch basemap
function switchBasemap(basemapKey) {
    if (basemapKey === currentBasemap) return;
    
    // Update UI
    document.querySelectorAll('.basemap-option').forEach(option => {
        option.classList.remove('active');
    });
    document.querySelector(`.basemap-option:nth-child(${Object.keys(basemaps).indexOf(basemapKey) + 1})`).classList.add('active');
    
    // Switch map layer
    map.removeLayer(basemapLayers[currentBasemap]);
    map.addLayer(basemapLayers[basemapKey]);
    currentBasemap = basemapKey;
    
    console.log(`🗺️ Switched to ${basemaps[basemapKey].name} basemap`);
}

// Toggle sidebar
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const toggleIcon = sidebar.querySelector('.sidebar-toggle i');
    
    sidebar.classList.toggle('collapsed');
    
    if (sidebar.classList.contains('collapsed')) {
        toggleIcon.className = 'fas fa-chevron-right';
    } else {
        toggleIcon.className = 'fas fa-chevron-left';
    }
}



// Update zoom display
function updateZoomDisplay() {
    const zoomElement = document.getElementById('zoomLevel');
    if (zoomElement) {
        zoomElement.textContent = currentZoom;
    }
}

// Initialize view info updater
function initializeViewInfoUpdater() {
    setInterval(() => {
        const bounds = map.getBounds();
        const latRange = (bounds.getNorth() - bounds.getSouth()).toFixed(3);
        const lonRange = (bounds.getEast() - bounds.getWest()).toFixed(3);
        
        const viewportElement = document.getElementById('viewportSize');
        if (viewportElement) {
            viewportElement.textContent = `${latRange}° × ${lonRange}°`;
        }
    }, 1000);
}

// Calculate optimal resolution based on zoom level and visible bounds
function calculateOptimalResolution() {
    const zoom = map.getZoom();
    const bounds = map.getBounds();
    
    const latRange = bounds.getNorth() - bounds.getSouth();
    const lonRange = bounds.getEast() - bounds.getWest();
    const visibleArea = latRange * lonRange;
    
    const zoomResolutionTable = {
        8: 0.02,
        9: 0.01,
        10: 0.005,
        11: 0.003,
        12: 0.002,
        13: 0.0015,
        14: 0.001,
        15: 0.0007,
        16: 0.0005,
        17: 0.0003,
        18: 0.0002
    };
    
    let baseResolution;
    if (zoomResolutionTable[zoom]) {
        baseResolution = zoomResolutionTable[zoom];
    } else {
        const zooms = Object.keys(zoomResolutionTable).map(Number).sort((a,b) => a-b);
        if (zoom < zooms[0]) baseResolution = zoomResolutionTable[zooms[0]];
        else if (zoom > zooms[zooms.length-1]) baseResolution = zoomResolutionTable[zooms[zooms.length-1]];
        else {
            let lowerZoom = zooms[0];
            let upperZoom = zooms[zooms.length-1];
            for (let i = 0; i < zooms.length - 1; i++) {
                if (zoom >= zooms[i] && zoom <= zooms[i+1]) {
                    lowerZoom = zooms[i];
                    upperZoom = zooms[i+1];
                    break;
                }
            }
            const lowerRes = zoomResolutionTable[lowerZoom];
            const upperRes = zoomResolutionTable[upperZoom];
            const t = (zoom - lowerZoom) / (upperZoom - lowerZoom);
            baseResolution = lowerRes + t * (upperRes - lowerRes);
        }
    }
    
    const MAX_CELLS = 25000;
    const visibleCells = (latRange / baseResolution) * (lonRange / baseResolution);
    
    if (visibleCells > MAX_CELLS) {
        const scaleFactor = Math.sqrt(MAX_CELLS / visibleCells);
        const adjustedResolution = baseResolution / scaleFactor;
        console.log(`📊 Area adjustment: ${visibleCells.toFixed(0)} cells → scaling resolution to ${adjustedResolution.toFixed(6)}`);
        return adjustedResolution;
    }
    
    console.log(`📏 Zoom ${zoom}, visible area: ${visibleArea.toFixed(4)}°², resolution: ${baseResolution.toFixed(6)}°`);
    return baseResolution;
}

// Get visible bounds for backend query
function getVisibleBounds() {
    const bounds = map.getBounds();
    return {
        north: bounds.getNorth(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        west: bounds.getWest()
    };
}

// Update status display
function updateStatus(message, type = 'ready') {
    const statusDiv = document.getElementById('status');
    statusDiv.textContent = message;
    statusDiv.className = `status-${type}`;
    console.log(`📢 ${type}: ${message}`);
}

// Fetch currents from backend with current view parameters
async function fetchCurrents(timeStr, timezone = 'EST') {
    try {
        updateStatus('Requesting tidal data from server...', 'loading');
        
        const resolution = calculateOptimalResolution();
        const bounds = getVisibleBounds();
        const zoom = map.getZoom();
        
        const params = new URLSearchParams({
            time: timeStr,
            timezone: timezone,
            resolution: resolution.toFixed(6),
            north: bounds.north.toFixed(6),
            south: bounds.south.toFixed(6),
            east: bounds.east.toFixed(6),
            west: bounds.west.toFixed(6)
        });
        
        const url = `/currents?${params.toString()}`;
        console.log('🌐 Fetching from:', url);
        
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (!data.success) {
            throw new Error(data.error || 'Unknown error from backend');
        }
        
        // Update grid cells display
        const gridCellsElement = document.getElementById('gridCells');
        if (gridCellsElement && data.shape) {
            const totalCells = data.shape[0] * data.shape[1];
            gridCellsElement.textContent = totalCells.toLocaleString();
        }
        
        updateStatus(`Loaded ${data.shape[0]}×${data.shape[1]} grid`, 'success');
        return data;
        
    } catch (error) {
        console.error('❌ API Error:', error);
        updateStatus(`Error: ${error.message}`, 'error');
        throw error;
    }
}

// Convert backend data to Leaflet.Velocity format
function convertToVelocityFormat(data) {
    const { U, V, lons, lats, shape } = data;
    const [rows, cols] = shape;
    
    console.log('🔄 Converting data:', { rows, cols, lats: lats?.length, lons: lons?.length });
    
    if (!U || !V || !lons || !lats) {
        console.error('❌ Missing data fields');
        return null;
    }
    
    if (lons.length < 2 || lats.length < 2) {
        console.error('❌ Insufficient grid points');
        return null;
    }
    
    const dx = lons[1] - lons[0];
    const dy = lats[1] - lats[0];
    
    const uFlat = [];
    const vFlat = [];
    
    for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
            const uVal = U[i] && U[i][j] !== undefined ? parseFloat(U[i][j]) : 0.0;
            const vVal = V[i] && V[i][j] !== undefined ? parseFloat(V[i][j]) : 0.0;
            uFlat.push(uVal);
            vFlat.push(vVal);
        }
    }
    
    const velocityData = [
        {
            header: {
                parameterUnit: "m.s-1",
                parameterNumber: 2,
                parameterNumberName: "Eastward current",
                parameterCategory: 2,
                dx: dx,
                dy: -Math.abs(dy),
                la1: lats[0],
                la2: lats[lats.length - 1],
                lo1: lons[0],
                lo2: lons[lons.length - 1],
                nx: cols,
                ny: rows,
                refTime: new Date().toISOString().replace('T', ' ')
            },
            data: uFlat
        },
        {
            header: {
                parameterUnit: "m.s-1",
                parameterNumber: 3,
                parameterNumberName: "Northward current",
                parameterCategory: 2,
                dx: dx,
                dy: -Math.abs(dy),
                la1: lats[0],
                la2: lats[lats.length - 1],
                lo1: lons[0],
                lo2: lons[lons.length - 1],
                nx: cols,
                ny: rows,
                refTime: new Date().toISOString().replace('T', ' ')
            },
            data: vFlat
        }
    ];
    
    console.log('✅ Velocity data created');
    return velocityData;
}

// Create velocity layer
function createVelocityLayer(data) {
    console.log('🎨 Creating velocity layer...');
    
    if (velocityLayer) {
        map.removeLayer(velocityLayer);
        velocityLayer = null;
        console.log('🗑️ Removed previous layer');
    }
    
    try {
        const velocityData = convertToVelocityFormat(data);
        if (!velocityData) {
            throw new Error('Failed to convert data');
        }
        
        velocityLayer = L.velocityLayer({
            displayValues: true,
            displayOptions: {
                velocityType: 'Tidal Current',
                position: 'bottomright',
                emptyString: 'No current data',
                showCardinal: true,
                speedUnit: 'm/s',
                displayPosition: 'bottomright'
            },
            data: velocityData,
            minVelocity: 0,
            maxVelocity: 2.0,
            velocityScale: 0.01,
            particleAge: 50,
            particleMultiplier: 1/100,
            particleLineWidth: 1,
            frameRate: 35,
            opacity: 0.9,
            colorScale: [
                'rgb(36,104,180)',
                'rgb(60,157,194)',
                'rgb(128,205,193)',
                'rgb(175,240,91)',
                'rgb(254,217,42)',
                'rgb(255,170,0)',
                'rgb(255,69,0)'
            ]
        });
        
        if (currentsEnabled) {
            velocityLayer.addTo(map);
        }
        
        console.log('✅ Velocity layer added to map');
        
        if (data.lats && data.lons) {
            const bounds = L.latLngBounds([
                [data.lats[0], data.lons[0]],
                [data.lats[data.lats.length - 1], data.lons[data.lons.length - 1]]
            ]);
            map.fitBounds(bounds.pad(0.0));
        }
        
        return velocityLayer;
        
    } catch (error) {
        console.error('❌ Error creating velocity layer:', error);
        updateStatus('Failed to create visualization', 'error');
        return null;
    }
}

// Main function to load and display currents
async function loadCurrentData() {
    try {
        console.log('⏳ Loading current data...');
        document.getElementById('loadingOverlay').style.display = 'flex';
        
        const timeInput = document.getElementById('timeInput');
        const timeStr = timeInput.value; // Remove the .replace('T', ' ') here
        
        console.log('📅 Requesting time:', timeStr);
        
        isUpdatingFromZoom = true;
        
        const data = await fetchCurrents(timeStr, 'EST');
        
        createVelocityLayer(data);
        
        // Update time display
        const timeDisplay = document.getElementById('timeDisplay');
        if (timeDisplay) {
            timeDisplay.textContent = `${timeStr} EST | Zoom: ${currentZoom}`;
        }
        
        console.log('✅ Currents loaded');
        
    } catch (error) {
        console.error('❌ Load currents error:', error);
        updateStatus(`Failed: ${error.message}`, 'error');
        
    } finally {
        document.getElementById('loadingOverlay').style.display = 'none';
        setTimeout(() => {
            isUpdatingFromZoom = false;
        }, 1000);
    }
}

// Export functions
window.loadCurrentData = loadCurrentData;
window.toggleSidebar = toggleSidebar;
window.toggleCurrentsLayer = toggleCurrentsLayer;
window.toggleParticles = toggleParticles;
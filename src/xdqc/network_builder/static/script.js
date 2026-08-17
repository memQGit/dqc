/*
 * Copyright 2026 memQ Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

class QuantumNetworkBuilder {
    constructor() {
        this.svg = document.getElementById('network-canvas');
        this.mode = 'select';
        this.selectedProcessor = null;
        this.selectedQubitForEdit = null;
        this.selectedQubits = [];
        this.nextProcessorId = 0;
        this.nextQubitId = 1;
        this.processors = new Map();
        this.qubits = new Map();
        this.connections = [];
        this.history = []; // Track actions for undo
        
        // Drag state
        this.isDragging = false;
        this.draggedProcessor = null;
        this.dragOffset = { x: 0, y: 0 };
        
        this.initializeEventListeners();
        this.updateStatus();
        this.updateNetworkInfo();
    }
    
    initializeEventListeners() {
        // Button event listeners
        document.getElementById('add-processor').addEventListener('click', () => this.setMode('processor'));
        document.getElementById('add-qubit').addEventListener('click', () => this.setMode('qubit'));
        document.getElementById('local-connect').addEventListener('click', () => this.setMode('local-connect'));
        document.getElementById('remote-connect').addEventListener('click', () => this.setMode('remote-connect'));
        document.getElementById('undo').addEventListener('click', () => this.undo());
        document.getElementById('clear-all').addEventListener('click', () => this.clearAll());
        document.getElementById('export-network').addEventListener('click', () => this.saveNetwork());
        document.getElementById('generate-graph').addEventListener('click', () => this.generateGraph());
        document.getElementById('generate-homogeneous').addEventListener('click', () => this.generateHomogeneousNetwork());
        document.getElementById('generate-preset').addEventListener('click', () => this.generatePresetNetwork());
        
        // Canvas click event
        this.svg.addEventListener('click', (e) => this.handleCanvasClick(e));
        
        // Mouse events for dragging
        this.svg.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.svg.addEventListener('mouseup', (e) => this.handleMouseUp(e));
        this.svg.addEventListener('mouseleave', (e) => this.handleMouseUp(e));
        
        // Prevent default drag behavior
        this.svg.addEventListener('dragstart', (e) => e.preventDefault());
        
        // QPU size change
        document.getElementById('qpu-size').addEventListener('change', () => {
            this.repositionAllQubits();
            this.updateStatus();
        });
    }
    
    setMode(newMode) {
        this.mode = newMode;
        this.clearSelection();
        this.updateButtonStates();
        this.updateStatus();
        
        // Special handling for processor mode - add immediately
        if (newMode === 'processor') {
            this.addProcessorAtCenter();
            this.mode = 'select'; // Reset to select mode after adding
            this.updateButtonStates();
            this.updateStatus();
        }
        
        // Enable/disable add qubit button based on processor selection
        const addQubitBtn = document.getElementById('add-qubit');
        addQubitBtn.disabled = this.selectedProcessor === null;
    }
    
    updateButtonStates() {
        const buttons = ['add-processor', 'add-qubit', 'local-connect', 'remote-connect'];
        buttons.forEach(btnId => {
            const btn = document.getElementById(btnId);
            btn.classList.remove('active');
        });
        
        // Only highlight connection modes when active
        if (this.mode === 'local-connect' || this.mode === 'remote-connect') {
            document.getElementById(this.mode).classList.add('active');
        }
    }
    
    updateStatus() {
        const modeTexts = {
            'processor': 'Adding processor...',
            'select': 'Click a processor to select it, then use buttons to add qubits or make connections',
            'local-connect': 'Click two qubits in the same processor to connect them',
            'remote-connect': 'Click two qubits in different processors to connect them'
        };
        
        document.getElementById('mode-status').textContent = modeTexts[this.mode] || modeTexts['select'];
        
        const selectedText = this.selectedProcessor !== null ? `Selected: Processor ${this.selectedProcessor}` : 'No processor selected';
        document.getElementById('selected-processor').textContent = selectedText;
    }
    
    handleCanvasClick(e) {
        // Only handle clicks for connection modes
        // Processor creation is now handled by button click
        // Qubit creation is handled by button click

        // Clicking blank canvas space clears the qubit edit highlight and processor selection.
        // Clicks on qubits/processors stopPropagation, so this only fires on empty space.
        this.clearQubitForEdit();
        this.clearProcessorSelection();
    }
    
    handleMouseDown(e) {
        // This is now handled by individual processor mousedown events
        // But keep this as fallback
    }
    
    handleMouseMove(e) {
        if (!this.isDragging || this.draggedProcessor === null) return;
        
        e.preventDefault();
        
        const { x, y } = this.getSvgPoint(e);
        
        const newX = x - this.dragOffset.x;
        const newY = y - this.dragOffset.y;
        
        // Use requestAnimationFrame for smooth updates
        requestAnimationFrame(() => {
            this.moveProcessor(this.draggedProcessor, newX, newY);
        });
    }
    
    handleMouseUp(e) {
        if (this.isDragging) {
            this.isDragging = false;
            this.draggedProcessor = null;
            this.svg.style.cursor = 'default';
        }
    }
    
    getProcessorAtPoint(x, y) {
        for (const [processorId, processor] of this.processors) {
            const halfWidth = processor.width / 2;
            const halfHeight = processor.height / 2;
            
            if (x >= processor.x - halfWidth && x <= processor.x + halfWidth &&
                y >= processor.y - halfHeight && y <= processor.y + halfHeight) {
                return processorId;
            }
        }
        return null;
    }
    
    moveProcessor(processorId, newX, newY) {
        const processor = this.processors.get(processorId);
        if (!processor) return;
        
        // Update processor position data first
        processor.x = newX;
        processor.y = newY;
        
        const halfWidth = processor.width / 2;
        const halfHeight = processor.height / 2;
        
        // Update processor rectangle position
        processor.rect.setAttribute('x', newX - halfWidth);
        processor.rect.setAttribute('y', newY - halfHeight);
        
        // Update processor label position
        const label = processor.element.querySelector('text');
        if (label) {
            label.setAttribute('x', newX);
            label.setAttribute('y', newY - halfHeight - 10);
        }
        
        // Update all qubits in this processor
        processor.qubits.forEach((qubitId, index) => {
            const qubit = this.qubits.get(qubitId);
            if (!qubit) return;
            
            const newPosition = this.calculateQubitPosition(processor, index);
            
            // Update qubit data
            qubit.x = newPosition.x;
            qubit.y = newPosition.y;
            
            // Update qubit visual elements
            qubit.circle.setAttribute('cx', newPosition.x);
            qubit.circle.setAttribute('cy', newPosition.y);
            qubit.label.setAttribute('x', newPosition.x);
            qubit.label.setAttribute('y', newPosition.y);
        });
        
        // Update all connection lines last
        this.updateAllConnections();
    }
    
    updateAllConnections() {
        this.connections.forEach(conn => {
            const qubit1 = this.qubits.get(conn.qubit1);
            const qubit2 = this.qubits.get(conn.qubit2);
            
            if (qubit1 && qubit2) {
                conn.element.setAttribute('x1', qubit1.x);
                conn.element.setAttribute('y1', qubit1.y);
                conn.element.setAttribute('x2', qubit2.x);
                conn.element.setAttribute('y2', qubit2.y);
                this.updateConnectionLabelPosition(conn);
            }
        });
    }

    normalizeFidelity(value) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 1;
        }
        return Math.min(1, Math.max(0, parsed));
    }

    formatFidelity(value) {
        const normalized = this.normalizeFidelity(value);
        return Number.isInteger(normalized) ? `${normalized}` : normalized.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
    }

    getConnectionDisplayName(conn) {
        const qubit1 = this.qubits.get(conn.qubit1);
        const qubit2 = this.qubits.get(conn.qubit2);
        const label1 = qubit1 ? qubit1.label.textContent : conn.qubit1;
        const label2 = qubit2 ? qubit2.label.textContent : conn.qubit2;
        const processor1 = qubit1 ? `P${qubit1.processorId}` : '';
        const processor2 = qubit2 ? `P${qubit2.processorId}` : '';
        return `${processor1}:${label1} to ${processor2}:${label2}`;
    }

    createConnectionLabel(conn) {
        if (conn.type !== 'remote') {
            return null;
        }

        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('class', 'remote-fidelity-label');
        label.textContent = this.formatFidelity(conn.fidelity);
        this.svg.insertBefore(label, conn.element.nextSibling);
        return label;
    }

    updateConnectionLabelPosition(conn) {
        if (!conn.label) {
            return;
        }

        const qubit1 = this.qubits.get(conn.qubit1);
        const qubit2 = this.qubits.get(conn.qubit2);
        if (!qubit1 || !qubit2) {
            return;
        }

        conn.label.setAttribute('x', (qubit1.x + qubit2.x) / 2);
        conn.label.setAttribute('y', ((qubit1.y + qubit2.y) / 2) - 8);
    }

    updateConnectionFidelityDisplay(conn) {
        if (conn.type !== 'remote') {
            return;
        }

        const fidelity = this.normalizeFidelity(conn.fidelity);
        conn.fidelity = fidelity;
        conn.element.setAttribute('data-fidelity', this.formatFidelity(fidelity));
        conn.element.setAttribute('stroke-opacity', Math.max(0.25, fidelity));
        conn.element.setAttribute('stroke-width', 2 + fidelity);

        let title = conn.element.querySelector('title');
        if (!title) {
            title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
            conn.element.appendChild(title);
        }
        title.textContent = `${this.getConnectionDisplayName(conn)} fidelity ${this.formatFidelity(fidelity)}`;

        if (conn.label) {
            conn.label.textContent = this.formatFidelity(fidelity);
            this.updateConnectionLabelPosition(conn);
        }
    }

    setConnectionFidelity(index, value) {
        const conn = this.connections[index];
        if (!conn || conn.type !== 'remote') {
            return;
        }

        conn.fidelity = this.normalizeFidelity(value);
        this.updateConnectionFidelityDisplay(conn);
        this.updateNetworkInfo(true);
    }

    normalizeCoherenceTime(value) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return 100;
        }
        return Math.max(0, parsed);
    }

    formatCoherenceTime(value) {
        const normalized = this.normalizeCoherenceTime(value);
        return Number.isInteger(normalized) ? `${normalized}` : normalized.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    }

    createDefaultQubitFields() {
        return {
            coherenceTime: 100,
            coherenceTimeUnit: 'us'
        };
    }

    getCoherenceVisualScale(value) {
        return Math.min(1, this.normalizeCoherenceTime(value) / 1000);
    }

    interpolateColor(start, end, amount) {
        const startInt = parseInt(start.slice(1), 16);
        const endInt = parseInt(end.slice(1), 16);
        const sr = (startInt >> 16) & 255;
        const sg = (startInt >> 8) & 255;
        const sb = startInt & 255;
        const er = (endInt >> 16) & 255;
        const eg = (endInt >> 8) & 255;
        const eb = endInt & 255;
        const r = Math.round(sr + (er - sr) * amount);
        const g = Math.round(sg + (eg - sg) * amount);
        const b = Math.round(sb + (eb - sb) * amount);
        return `rgb(${r}, ${g}, ${b})`;
    }

    getCoherenceColor(value) {
        const scale = this.getCoherenceVisualScale(value);
        if (scale < 0.5) {
            return this.interpolateColor('#ef5b6d', '#ec4899', scale / 0.5);
        }
        return this.interpolateColor('#ec4899', '#58a6ff', (scale - 0.5) / 0.5);
    }

    updateQubitCoherenceVisual(qubit) {
        if (!qubit || !qubit.circle) {
            return;
        }

        const scale = this.getCoherenceVisualScale(qubit.coherenceTime);
        const color = this.getCoherenceColor(qubit.coherenceTime);
        qubit.circle.style.fill = color;
        qubit.circle.style.stroke = color;
        qubit.circle.style.fillOpacity = `${0.24 + (scale * 0.46)}`;
        qubit.circle.style.strokeWidth = `${2 + (scale * 2)}`;
        qubit.circle.style.filter = `drop-shadow(0 0 ${2 + (scale * 7)}px ${color})`;

        let title = qubit.circle.querySelector('title');
        if (!title) {
            title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
            qubit.circle.appendChild(title);
        }
        title.textContent = `${this.getQubitDisplayNameForData(qubit)} T2 ${this.formatCoherenceTime(qubit.coherenceTime)} ${qubit.coherenceTimeUnit || 'us'}`;
    }

    getQubitDisplayNameForData(qubit) {
        return `P${qubit.processorId}:${qubit.label ? qubit.label.textContent : 'qubit'}`;
    }

    getQubitDisplayName(qubitId) {
        const qubit = this.qubits.get(qubitId);
        if (!qubit) {
            return `q${qubitId}`;
        }
        return `P${qubit.processorId}:${qubit.label.textContent}`;
    }

    selectQubitForEdit(qubitId) {
        if (this.selectedQubitForEdit !== null) {
            const previous = this.qubits.get(this.selectedQubitForEdit);
            if (previous) {
                previous.circle.classList.remove('editing');
            }
        }

        this.selectedQubitForEdit = qubitId;
        const qubit = this.qubits.get(qubitId);
        if (qubit) {
            qubit.circle.classList.add('editing');
            this.updateQubitCoherenceVisual(qubit);
        }

        this.updateQubitCoherenceControls();
        this.updateNetworkInfo(true);
    }

    clearQubitForEdit() {
        if (this.selectedQubitForEdit === null) {
            return;
        }

        const previous = this.qubits.get(this.selectedQubitForEdit);
        if (previous) {
            previous.circle.classList.remove('editing');
        }

        this.selectedQubitForEdit = null;
        this.updateQubitCoherenceControls();
        this.updateNetworkInfo(true);
    }

    setQubitCoherenceTime(qubitId, value) {
        const qubit = this.qubits.get(qubitId);
        if (!qubit) {
            return;
        }

        qubit.coherenceTime = this.normalizeCoherenceTime(value);
        this.updateQubitCoherenceVisual(qubit);
        this.updateQubitCoherenceControls();
        this.updateNetworkInfo(true, true);
    }
    
    addProcessorAtCenter() {
        // Find a good position for the new processor
        const canvasWidth = this.svg.getAttribute('width');
        const canvasHeight = this.svg.getAttribute('height');
        const processorWidth = 200;
        const processorHeight = 150;
        
        // Try to place processors in a grid pattern
        const cols = Math.floor(canvasWidth / (processorWidth + 50));
        const processorCount = this.processors.size;
        const row = Math.floor(processorCount / cols);
        const col = processorCount % cols;
        
        const x = 150 + col * (processorWidth + 50);
        const y = 150 + row * (processorHeight + 50);
        
        this.addProcessor(x, y);
    }
    
    addProcessor(x, y) {
        const processorId = this.nextProcessorId++;
        const width = 200;
        const height = 150;
        
        // Create processor group
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'processor-group');
        
        // Create processor rectangle
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', x - width/2);
        rect.setAttribute('y', y - height/2);
        rect.setAttribute('width', width);
        rect.setAttribute('height', height);
        rect.setAttribute('rx', 10);
        rect.setAttribute('class', 'processor');
        rect.setAttribute('data-processor-id', processorId);
        
        // Create processor label
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', x);
        label.setAttribute('y', y - height/2 - 10);
        label.setAttribute('class', 'processor-label');
        label.textContent = `P${processorId}`;
        
        // Add click handler for processor selection
        rect.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!this.isDragging) {
                // Clicking the already-selected processor again toggles it off
                if (this.selectedProcessor === processorId) {
                    this.clearProcessorSelection();
                } else {
                    this.selectProcessor(processorId);
                }
            }
        });
        
        // Add mousedown handler for dragging
        rect.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const { x, y } = this.getSvgPoint(e);
            
            this.isDragging = true;
            this.draggedProcessor = processorId;
            const processor = this.processors.get(processorId);
            this.dragOffset.x = x - processor.x;
            this.dragOffset.y = y - processor.y;
            
            // Change cursor
            this.svg.style.cursor = 'grabbing';
        });
        
        group.appendChild(rect);
        group.appendChild(label);
        this.svg.appendChild(group);
        
        // Store processor data
        this.processors.set(processorId, {
            element: group,
            rect: rect,
            x: x,
            y: y,
            width: width,
            height: height,
            qubits: []
        });
        
        // Add to history for undo
        this.history.push({
            type: 'processor',
            id: processorId,
            data: { x, y, width, height }
        });
        
        this.selectProcessor(processorId);
        this.updateNetworkInfo();
    }

    getSvgPoint(e) {
        const point = this.svg.createSVGPoint();
        point.x = e.clientX;
        point.y = e.clientY;

        const matrix = this.svg.getScreenCTM();
        if (!matrix) {
            return { x: 0, y: 0 };
        }

        return point.matrixTransform(matrix.inverse());
    }
    
    selectProcessor(processorId) {
        // Clear previous selection
        this.processors.forEach((proc, id) => {
            proc.rect.classList.remove('selected');
        });
        
        // Select new processor
        this.selectedProcessor = processorId;
        const processor = this.processors.get(processorId);
        processor.rect.classList.add('selected');
        
        // Enable add qubit button
        document.getElementById('add-qubit').disabled = false;

        this.updateStatus();
    }

    clearProcessorSelection() {
        if (this.selectedProcessor === null) {
            return;
        }

        this.processors.forEach((proc) => {
            proc.rect.classList.remove('selected');
        });

        this.selectedProcessor = null;
        document.getElementById('add-qubit').disabled = true;
        this.updateStatus();
    }

    addQubit() {
        if (this.selectedProcessor === null) {
            alert('Please select a processor first');
            return;
        }
        
        const processor = this.processors.get(this.selectedProcessor);
        const qpuSize = parseInt(document.getElementById('qpu-size').value);
        
        if (processor.qubits.length >= qpuSize) {
            alert(`Processor ${this.selectedProcessor} is full (max ${qpuSize} qubits)`);
            return;
        }
        
        const qubitId = this.nextQubitId++;
        const position = this.calculateQubitPosition(processor, processor.qubits.length);
        
        // Create qubit group
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'qubit-group');
        
        // Create qubit circle
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', position.x);
        circle.setAttribute('cy', position.y);
        circle.setAttribute('r', 15);
        circle.setAttribute('class', 'qubit');
        circle.setAttribute('data-qubit-id', qubitId);
        
        // Create qubit label
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', position.x);
        label.setAttribute('y', position.y);
        label.setAttribute('class', 'qubit-label');
        label.textContent = 'q0';
        
        // Add click handler for qubit selection
        circle.addEventListener('click', (e) => {
            e.stopPropagation();
            this.handleQubitClick(qubitId);
        });
        
        group.appendChild(circle);
        group.appendChild(label);
        this.svg.appendChild(group);
        
        // Store qubit data
        const qubitData = {
            element: group,
            circle: circle,
            label: label,
            x: position.x,
            y: position.y,
            processorId: this.selectedProcessor,
            localConnections: [],
            remoteConnections: [],
            ...this.createDefaultQubitFields()
        };
        
        this.qubits.set(qubitId, qubitData);
        processor.qubits.push(qubitId);
        this.refreshProcessorQubitLabels(this.selectedProcessor);
        this.updateQubitCoherenceVisual(qubitData);
        
        // Add to history for undo
        this.history.push({
            type: 'qubit',
            id: qubitId,
            processorId: this.selectedProcessor,
            data: { x: position.x, y: position.y }
        });
        
        this.updateNetworkInfo();
    }
    
    getQubitKind(qubit) {
        return qubit.remoteConnections.length > 0 ? 'communication' : 'computation';
    }

    formatQubitDisplayLabel(processorId, kind, localIndex) {
        const prefix = kind === 'communication' ? 'c' : 'q';
        return `${prefix}${localIndex}`;
    }

    refreshProcessorQubitLabels(processorId) {
        const processor = this.processors.get(processorId);
        if (!processor) return;

        const kindCounters = {
            computation: 0,
            communication: 0
        };

        processor.qubits.forEach((qubitId) => {
            const qubit = this.qubits.get(qubitId);
            if (!qubit) return;

            const kind = this.getQubitKind(qubit);
            const localIndex = kindCounters[kind];
            kindCounters[kind] += 1;
            qubit.label.textContent = this.formatQubitDisplayLabel(processorId, kind, localIndex);
            this.updateQubitCoherenceVisual(qubit);
        });
    }

    updateQubitLabel(qubitId) {
        const qubit = this.qubits.get(qubitId);
        if (!qubit) return;
        this.refreshProcessorQubitLabels(qubit.processorId);
    }
    
    calculateQubitPosition(processor, qubitIndex) {
        const qpuSize = parseInt(document.getElementById('qpu-size').value);
        const cols = Math.ceil(Math.sqrt(qpuSize));
        const rows = Math.ceil(qpuSize / cols);
        
        const row = Math.floor(qubitIndex / cols);
        const col = qubitIndex % cols;
        
        // Use more of the processor space with better spacing
        const usableWidth = processor.width * 0.7;  // 70% of processor width
        const usableHeight = processor.height * 0.7; // 70% of processor height
        
        const colSpacing = cols > 1 ? usableWidth / (cols - 1) : 0;
        const rowSpacing = rows > 1 ? usableHeight / (rows - 1) : 0;
        
        const startX = processor.x - usableWidth / 2;
        const startY = processor.y - usableHeight / 2;
        
        return {
            x: startX + col * colSpacing,
            y: startY + row * rowSpacing
        };
    }
    
    repositionAllQubits() {
        // Reposition qubits in each processor based on new QPU size
        this.processors.forEach((processor, processorId) => {
            processor.qubits.forEach((qubitId, index) => {
                const qubit = this.qubits.get(qubitId);
                if (!qubit) return;
                
                const newPosition = this.calculateQubitPosition(processor, index);
                
                // Update circle position
                qubit.circle.setAttribute('cx', newPosition.x);
                qubit.circle.setAttribute('cy', newPosition.y);
                
                // Update label position
                qubit.label.setAttribute('x', newPosition.x);
                qubit.label.setAttribute('y', newPosition.y);
                
                // Update stored position
                qubit.x = newPosition.x;
                qubit.y = newPosition.y;
            });
        });
        
        // Update connection line positions
        this.connections.forEach(conn => {
            const qubit1 = this.qubits.get(conn.qubit1);
            const qubit2 = this.qubits.get(conn.qubit2);
            
            if (qubit1 && qubit2) {
                conn.element.setAttribute('x1', qubit1.x);
                conn.element.setAttribute('y1', qubit1.y);
                conn.element.setAttribute('x2', qubit2.x);
                conn.element.setAttribute('y2', qubit2.y);
                this.updateConnectionLabelPosition(conn);
            }
        });
    }
    
    handleQubitClick(qubitId) {
        if (this.mode === 'local-connect' || this.mode === 'remote-connect') {
            this.toggleQubitSelection(qubitId);
            return;
        }

        // Clicking the already-selected qubit again toggles the highlight off
        if (this.selectedQubitForEdit === qubitId) {
            this.clearQubitForEdit();
            return;
        }

        this.selectQubitForEdit(qubitId);
    }
    
    removeQubit(qubitId) {
        if (!confirm('Remove this qubit and all its connections?')) {
            return;
        }
        
        const qubit = this.qubits.get(qubitId);
        if (!qubit) return;
        
        // Remove all connections involving this qubit
        this.connections = this.connections.filter(conn => {
            if (conn.qubit1 === qubitId || conn.qubit2 === qubitId) {
                conn.element.remove();
                if (conn.label) {
                    conn.label.remove();
                }
                return false;
            }
            return true;
        });
        
        // Remove from other qubits' connection lists
        this.qubits.forEach((otherQubit, otherId) => {
            if (otherId !== qubitId) {
                otherQubit.localConnections = otherQubit.localConnections.filter(id => id !== qubitId);
                otherQubit.remoteConnections = otherQubit.remoteConnections.filter(id => id !== qubitId);
            }
        });
        
        // Remove from processor's qubit list
        const processor = this.processors.get(qubit.processorId);
        if (processor) {
            processor.qubits = processor.qubits.filter(id => id !== qubitId);
        }
        
        // Remove visual element
        qubit.element.remove();
        
        // Remove from data structure
        this.qubits.delete(qubitId);
        if (this.selectedQubitForEdit === qubitId) {
            this.selectedQubitForEdit = null;
        }
        this.processors.forEach((_, processorId) => this.refreshProcessorQubitLabels(processorId));
        
        this.updateNetworkInfo();
        this.updateRemoteLinkControls();
        this.updateQubitCoherenceControls();
    }
    
    toggleQubitSelection(qubitId) {
        const qubit = this.qubits.get(qubitId);
        const index = this.selectedQubits.indexOf(qubitId);
        
        if (index === -1) {
            // Select qubit
            this.selectedQubits.push(qubitId);
            qubit.circle.classList.add('selected');
        } else {
            // Deselect qubit
            this.selectedQubits.splice(index, 1);
            qubit.circle.classList.remove('selected');
        }
        
        // If we have two selected qubits, try to connect them
        if (this.selectedQubits.length === 2) {
            this.createConnection();
        }
    }
    
    createConnection() {
        const [qubit1Id, qubit2Id] = this.selectedQubits;
        const qubit1 = this.qubits.get(qubit1Id);
        const qubit2 = this.qubits.get(qubit2Id);
        
        const sameProcessor = qubit1.processorId === qubit2.processorId;
        
        // Validate connection type
        if (this.mode === 'local-connect' && !sameProcessor) {
            alert('Local connections must be within the same processor');
            this.clearSelection();
            return;
        }
        
        if (this.mode === 'remote-connect' && sameProcessor) {
            alert('Remote connections must be between different processors');
            this.clearSelection();
            return;
        }
        
        // Check if connection already exists
        const connectionExists = this.connections.some(conn => 
            (conn.qubit1 === qubit1Id && conn.qubit2 === qubit2Id) ||
            (conn.qubit1 === qubit2Id && conn.qubit2 === qubit1Id)
        );
        
        if (connectionExists) {
            alert('Connection already exists between these qubits');
            this.clearSelection();
            return;
        }
        
        // Create visual connection
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', qubit1.x);
        line.setAttribute('y1', qubit1.y);
        line.setAttribute('x2', qubit2.x);
        line.setAttribute('y2', qubit2.y);
        const connectionType = this.mode === 'local-connect' ? 'local' : 'remote';
        line.setAttribute('class', connectionType === 'local' ? 'local-connection' : 'remote-connection');
        
        // Insert line after the grid but before other elements so it appears below qubits
        const gridRect = this.svg.querySelector('rect');
        this.svg.insertBefore(line, gridRect.nextSibling);
        
        // Store connection data
        const connectionData = {
            element: line,
            qubit1: qubit1Id,
            qubit2: qubit2Id,
            type: connectionType,
            fidelity: connectionType === 'remote' ? 1 : undefined,
            label: null
        };

        connectionData.label = this.createConnectionLabel(connectionData);
        this.updateConnectionFidelityDisplay(connectionData);
        
        this.connections.push(connectionData);
        
        // Update qubit connection lists
        if (connectionData.type === 'local') {
            qubit1.localConnections.push(qubit2Id);
            qubit2.localConnections.push(qubit1Id);
        } else {
            qubit1.remoteConnections.push(qubit2Id);
            qubit2.remoteConnections.push(qubit1Id);
            this.refreshProcessorQubitLabels(qubit1.processorId);
            this.refreshProcessorQubitLabels(qubit2.processorId);
        }
        
        // Add to history for undo
        this.history.push({
            type: 'connection',
            qubit1: qubit1Id,
            qubit2: qubit2Id,
            connectionType: connectionData.type
        });
        
        this.clearSelection();
        this.updateNetworkInfo();
        this.updateRemoteLinkControls();
    }
    
    removeQubit(qubitId) {
        if (!confirm('Remove this qubit and all its connections?')) {
            return;
        }
        
        const qubit = this.qubits.get(qubitId);
        if (!qubit) return;
        
        // Remove all connections involving this qubit
        this.connections = this.connections.filter(conn => {
            if (conn.qubit1 === qubitId || conn.qubit2 === qubitId) {
                conn.element.remove();
                if (conn.label) {
                    conn.label.remove();
                }
                return false;
            }
            return true;
        });
        
        // Remove from other qubits' connection lists
        this.qubits.forEach((otherQubit, otherId) => {
            if (otherId !== qubitId) {
                otherQubit.localConnections = otherQubit.localConnections.filter(id => id !== qubitId);
                otherQubit.remoteConnections = otherQubit.remoteConnections.filter(id => id !== qubitId);
            }
        });
        
        // Remove from processor's qubit list
        const processor = this.processors.get(qubit.processorId);
        if (processor) {
            processor.qubits = processor.qubits.filter(id => id !== qubitId);
        }
        
        // Remove visual element
        qubit.element.remove();
        
        // Remove from data structure
        this.qubits.delete(qubitId);
        this.processors.forEach((_, processorId) => this.refreshProcessorQubitLabels(processorId));
        
        this.updateNetworkInfo();
    }
    
    clearSelection() {
        this.selectedQubits.forEach(qubitId => {
            const qubit = this.qubits.get(qubitId);
            if (qubit) {
                qubit.circle.classList.remove('selected');
            }
        });
        this.selectedQubits = [];
    }
    
    clearAll() {
        if (confirm('Are you sure you want to clear the entire network?')) {
            // Remove all SVG elements except the grid
            while (this.svg.children.length > 1) {
                this.svg.removeChild(this.svg.lastChild);
            }
            
            // Reset data structures
            this.processors.clear();
            this.qubits.clear();
            this.connections = [];
            this.selectedQubits = [];
            this.selectedProcessor = null;
            this.selectedQubitForEdit = null;
            this.nextProcessorId = 0;
            this.nextQubitId = 1;
            this.history = [];
            
            // Reset UI
            document.getElementById('add-qubit').disabled = true;
            this.updateStatus();
            this.updateNetworkInfo();
            this.updateQubitCoherenceControls();
        }
    }
    
    undo() {
        if (this.history.length === 0) {
            alert('Nothing to undo');
            return;
        }
        
        const lastAction = this.history.pop();
        
        switch (lastAction.type) {
            case 'processor':
                this.removeProcessorById(lastAction.id);
                break;
            case 'qubit':
                this.removeQubitById(lastAction.id);
                break;
            case 'connection':
                this.removeConnectionBetween(lastAction.qubit1, lastAction.qubit2);
                break;
        }
        
        this.updateNetworkInfo();
    }
    
    removeProcessorById(processorId) {
        const processor = this.processors.get(processorId);
        if (!processor) return;
        
        // Remove all qubits in this processor first
        [...processor.qubits].forEach(qubitId => {
            this.removeQubitById(qubitId, false); // false = don't update history
        });
        
        // Remove visual element
        processor.element.remove();
        
        // Remove from data structure
        this.processors.delete(processorId);
        
        // Clear selection if this processor was selected
        if (this.selectedProcessor === processorId) {
            this.selectedProcessor = null;
            document.getElementById('add-qubit').disabled = true;
        }
    }
    
    removeQubitById(qubitId, updateHistory = true) {
        const qubit = this.qubits.get(qubitId);
        if (!qubit) return;
        
        // Remove all connections involving this qubit
        this.connections = this.connections.filter(conn => {
            if (conn.qubit1 === qubitId || conn.qubit2 === qubitId) {
                conn.element.remove();
                return false;
            }
            return true;
        });
        
        // Remove from other qubits' connection lists and update labels
        this.qubits.forEach((otherQubit, otherId) => {
            if (otherId !== qubitId) {
                otherQubit.localConnections = otherQubit.localConnections.filter(id => id !== qubitId);
                otherQubit.remoteConnections = otherQubit.remoteConnections.filter(id => id !== qubitId);
            }
        });
        
        // Remove from processor's qubit list
        const processor = this.processors.get(qubit.processorId);
        if (processor) {
            processor.qubits = processor.qubits.filter(id => id !== qubitId);
        }
        
        // Remove visual element
        qubit.element.remove();
        
        // Remove from data structure
        this.qubits.delete(qubitId);
        if (this.selectedQubitForEdit === qubitId) {
            this.selectedQubitForEdit = null;
        }
        this.processors.forEach((_, processorId) => this.refreshProcessorQubitLabels(processorId));
        this.updateRemoteLinkControls();
        this.updateQubitCoherenceControls();
    }
    
    removeConnectionBetween(qubit1Id, qubit2Id) {
        // Find and remove the connection
        const connectionIndex = this.connections.findIndex(conn => 
            (conn.qubit1 === qubit1Id && conn.qubit2 === qubit2Id) ||
            (conn.qubit1 === qubit2Id && conn.qubit2 === qubit1Id)
        );
        
        if (connectionIndex !== -1) {
            const connection = this.connections[connectionIndex];
            
            // Remove visual element
            connection.element.remove();
            if (connection.label) {
                connection.label.remove();
            }
            
            // Remove from connections array
            this.connections.splice(connectionIndex, 1);
            
            // Remove from qubits' connection lists
            const qubit1 = this.qubits.get(qubit1Id);
            const qubit2 = this.qubits.get(qubit2Id);
            
            if (qubit1 && qubit2) {
                if (connection.type === 'local') {
                    qubit1.localConnections = qubit1.localConnections.filter(id => id !== qubit2Id);
                    qubit2.localConnections = qubit2.localConnections.filter(id => id !== qubit1Id);
                } else {
                    qubit1.remoteConnections = qubit1.remoteConnections.filter(id => id !== qubit2Id);
                    qubit2.remoteConnections = qubit2.remoteConnections.filter(id => id !== qubit1Id);
                    this.refreshProcessorQubitLabels(qubit1.processorId);
                    this.refreshProcessorQubitLabels(qubit2.processorId);
                }
            }
            this.updateRemoteLinkControls();
        }
    }
    
    formatQubitCanonicalId(processorId, kind, localIndex) {
        const prefix = kind === 'communication' ? 'c' : 'q';
        return `${prefix}_${processorId}_${localIndex}`;
    }

    serializeCurrentNetwork() {
        const network = {
            processors: {},
            qubits: {},
            connections: []
        };

        const idMap = new Map();
        const processorIdMap = new Map();
        const sortedProcessorIds = Array.from(this.processors.keys()).sort((a, b) => a - b);
        sortedProcessorIds.forEach((oldId, newId) => {
            processorIdMap.set(oldId, newId);
        });

        sortedProcessorIds.forEach((oldProcessorId) => {
            const processor = this.processors.get(oldProcessorId);
            const qubitIds = processor.qubits.slice();
            const kindCounters = {
                computation: 0,
                communication: 0
            };
            const processorId = processorIdMap.get(oldProcessorId);

            network.processors[processorId] = {
                id: processorId,
                qubits: {
                    computation: [],
                    communication: []
                }
            };

            qubitIds.forEach((rawQubitId) => {
                const qubit = this.qubits.get(rawQubitId);
                const kind = qubit.remoteConnections.length > 0 ? 'communication' : 'computation';
                const localIndex = kindCounters[kind];
                kindCounters[kind] += 1;

                const canonicalId = this.formatQubitCanonicalId(processorId, kind, localIndex);
                idMap.set(rawQubitId, canonicalId);
                network.processors[processorId].qubits[kind].push(canonicalId);

                network.qubits[canonicalId] = {
                    id: canonicalId,
                    kind: kind,
                    type: kind,
                    processorId: processorId,
                    localIndex: localIndex,
                    label: `${kind === 'communication' ? 'c' : 'q'}(${processorId},${localIndex})`,
                    coherenceTime: this.normalizeCoherenceTime(qubit.coherenceTime),
                    coherenceTimeUnit: qubit.coherenceTimeUnit || 'us',
                    localConnections: [],
                    remoteConnections: []
                };
            });
        });

        this.qubits.forEach((qubit, rawQubitId) => {
            const canonicalId = idMap.get(rawQubitId);
            if (!canonicalId) {
                return;
            }

            network.qubits[canonicalId].localConnections = qubit.localConnections
                .map((otherRawId) => idMap.get(otherRawId))
                .filter((id) => Boolean(id));

            network.qubits[canonicalId].remoteConnections = qubit.remoteConnections
                .map((otherRawId) => idMap.get(otherRawId))
                .filter((id) => Boolean(id));
        });

        this.connections.forEach((conn) => {
            const q1 = idMap.get(conn.qubit1);
            const q2 = idMap.get(conn.qubit2);
            if (!q1 || !q2) {
                return;
            }
            network.connections.push({
                qubit1: q1,
                qubit2: q2,
                type: conn.type,
                ...(conn.type === 'remote' ? { fidelity: this.normalizeFidelity(conn.fidelity) } : {})
            });
        });

        return network;
    }

    createConnectionRecord(q1, q2, type, fidelity = 1) {
        return {
            qubit1: q1,
            qubit2: q2,
            type: type,
            ...(type === 'remote' ? { fidelity: this.normalizeFidelity(fidelity) } : {})
        };
    }

    createQubitRecord(id, kind, processorId, localIndex) {
        return {
            id: id,
            kind: kind,
            type: kind,
            processorId: processorId,
            localIndex: localIndex,
            label: `${kind === 'communication' ? 'c' : 'q'}(${processorId},${localIndex})`,
            ...this.createDefaultQubitFields(),
            localConnections: [],
            remoteConnections: []
        };
    }

    saveNetwork() {
        const filename = prompt('Enter filename for the network (without .json extension):', `quantum_network_${Date.now()}`);
        
        if (!filename) {
            return; // User cancelled
        }

        const network = this.serializeCurrentNetwork();
        this.downloadNetworkJson(network, filename);
    }

    generateHomogeneousNetwork() {
        const compPerQpu = parseInt(document.getElementById('bulk-comp-qubits').value, 10);
        const qpuCount = parseInt(document.getElementById('bulk-qpu-count').value, 10);
        const commPerLink = parseInt(document.getElementById('bulk-comm-qubits').value, 10);
        
        if (!Number.isInteger(compPerQpu) || compPerQpu < 1) {
            alert('Computational qubits per QPU must be at least 1.');
            return;
        }
        
        if (!Number.isInteger(qpuCount) || qpuCount < 1) {
            alert('Number of QPUs must be at least 1.');
            return;
        }
        
        if (!Number.isInteger(commPerLink) || commPerLink < 0) {
            alert('Communication qubits per link must be 0 or more.');
            return;
        }
        
        const network = this.buildHomogeneousLineNetwork(compPerQpu, qpuCount, commPerLink);
        const filename = prompt('Enter filename for the network (without .json extension):', `homogeneous_network_${Date.now()}`);
        
        if (!filename) {
            return;
        }
        
        this.downloadNetworkJson(network, filename);
    }

    generatePresetNetwork() {
        const qpuCount = parseInt(document.getElementById('bulk-qpu-count').value, 10);
        const presetType = document.getElementById('preset-network-type').value;
        const gridColumns = parseInt(document.getElementById('preset-grid-columns').value, 10);

        if (!Number.isInteger(qpuCount) || qpuCount < 1) {
            alert('Number of QPUs must be at least 1.');
            return;
        }

        let network = null;
        let filenamePrefix = '';

        if (presetType === 'ring-large') {
            network = this.buildRingLargeNetwork(qpuCount);
            filenamePrefix = 'ring_large_network';
        } else if (presetType === 'ring-small') {
            network = this.buildRingSmallNetwork(qpuCount);
            filenamePrefix = 'ring_small_network';
        } else if (presetType === 'ring-tiny') {
            network = this.buildRingTinyNetwork(qpuCount);
            filenamePrefix = 'ring_tiny_network';
        } else if (presetType === 'hub-large') {
            network = this.buildHubLargeNetwork(qpuCount);
            filenamePrefix = 'hub_large_network';
        } else if (presetType === 'hub-small') {
            network = this.buildHubSmallNetwork(qpuCount);
            filenamePrefix = 'hub_small_network';
        } else if (presetType === 'hub-tiny') {
            network = this.buildHubTinyNetwork(qpuCount);
            filenamePrefix = 'hub_tiny_network';
        } else if (presetType === 'all-to-all-large') {
            network = this.buildAllToAllLargeNetwork(qpuCount);
            filenamePrefix = 'all_to_all_large_network';
        } else if (presetType === 'all-to-all-small') {
            network = this.buildAllToAllSmallNetwork(qpuCount);
            filenamePrefix = 'all_to_all_small_network';
        } else if (presetType === 'all-to-all-tiny') {
            network = this.buildAllToAllTinyNetwork(qpuCount);
            filenamePrefix = 'all_to_all_tiny_network';
        } else if (presetType === 'grid-large') {
            if (!Number.isInteger(gridColumns) || gridColumns < 1) {
                alert('Grid columns must be at least 1.');
                return;
            }
            network = this.buildGridLargeNetwork(qpuCount, gridColumns);
            filenamePrefix = 'grid_large_network';
        } else if (presetType === 'grid-small') {
            if (!Number.isInteger(gridColumns) || gridColumns < 1) {
                alert('Grid columns must be at least 1.');
                return;
            }
            network = this.buildGridSmallNetwork(qpuCount, gridColumns);
            filenamePrefix = 'grid_small_network';
        } else if (presetType === 'grid-tiny') {
            if (!Number.isInteger(gridColumns) || gridColumns < 1) {
                alert('Grid columns must be at least 1.');
                return;
            }
            network = this.buildGridTinyNetwork(qpuCount, gridColumns);
            filenamePrefix = 'grid_tiny_network';
        } else {
            alert('Unknown preset network type selected.');
            return;
        }

        const filename = prompt(
            'Enter filename for the network (without .json extension):',
            `${filenamePrefix}_${Date.now()}`
        );

        if (!filename) {
            return;
        }

        this.downloadNetworkJson(network, filename);
    }

    buildHomogeneousLineNetwork(compPerQpu, qpuCount, commPerLink) {
        const network = {
            processors: {},
            qubits: {},
            connections: []
        };

        const kindCounters = {};

        for (let p = 0; p < qpuCount; p += 1) {
            network.processors[p] = {
                id: p,
                qubits: {
                    computation: [],
                    communication: []
                }
            };
            kindCounters[p] = {
                computation: 0,
                communication: 0
            };
        }

        const createQubit = (processorId, kind) => {
            const localIndex = kindCounters[processorId][kind];
            kindCounters[processorId][kind] += 1;
            const id = this.formatQubitCanonicalId(processorId, kind, localIndex);

            network.qubits[id] = this.createQubitRecord(id, kind, processorId, localIndex);
            network.processors[processorId].qubits[kind].push(id);
            return id;
        };

        for (let p = 0; p < qpuCount; p += 1) {
            for (let i = 0; i < compPerQpu; i += 1) {
                createQubit(p, 'computation');
            }
        }
        
        if (qpuCount > 1 && commPerLink > 0) {
            for (let p = 0; p < qpuCount - 1; p += 1) {
                for (let i = 0; i < commPerLink; i += 1) {
                    const leftId = createQubit(p, 'communication');
                    const rightId = createQubit(p + 1, 'communication');
                    
                    network.qubits[leftId].remoteConnections.push(rightId);
                    network.qubits[rightId].remoteConnections.push(leftId);
                    
                    network.connections.push(this.createConnectionRecord(leftId, rightId, 'remote'));
                }
            }
        }
        
        return network;
    }

    buildRingLargeNetwork(qpuCount) {
        const {
            network,
            topCommByProcessor,
            bottomCommByProcessor,
            connectQubits
        } = this.buildLargeQpuBase(qpuCount);

        if (qpuCount === 2) {
            for (let i = 0; i < 4; i += 1) {
                connectQubits(topCommByProcessor[0][i], topCommByProcessor[1][i], 'remote');
                connectQubits(bottomCommByProcessor[0][i], bottomCommByProcessor[1][i], 'remote');
            }
        } else {
            for (let p = 0; p < qpuCount - 1; p += 1) {
                for (let i = 0; i < 4; i += 1) {
                    connectQubits(bottomCommByProcessor[p][i], topCommByProcessor[p + 1][i], 'remote');
                }
            }

            // Close the chain by directly linking the first and last processors.
            const firstProcessor = 0;
            const lastProcessor = qpuCount - 1;
            for (let i = 0; i < 4; i += 1) {
                connectQubits(topCommByProcessor[firstProcessor][i], topCommByProcessor[lastProcessor][i], 'remote');
                connectQubits(bottomCommByProcessor[firstProcessor][i], bottomCommByProcessor[lastProcessor][i], 'remote');
            }
        }

        if (qpuCount > 2) {
            // Keep extra long-range links for interior processors.
            for (let p = 1; p < qpuCount - 2; p += 1) {
                for (let i = 0; i < 4; i += 1) {
                    connectQubits(topCommByProcessor[p][i], bottomCommByProcessor[p + 2][i], 'remote');
                }
            }
        }

        return network;
    }

    buildLargeQpuBase(qpuCount) {
        const network = {
            processors: {},
            qubits: {},
            connections: []
        };

        const topCommByProcessor = {};
        const bottomCommByProcessor = {};
        const kindCounters = {};

        for (let p = 0; p < qpuCount; p += 1) {
            network.processors[p] = {
                id: p,
                qubits: {
                    computation: [],
                    communication: []
                }
            };
            kindCounters[p] = {
                computation: 0,
                communication: 0
            };
        }

        const createQubit = (processorId, kind) => {
            const localIndex = kindCounters[processorId][kind];
            kindCounters[processorId][kind] += 1;
            const id = this.formatQubitCanonicalId(processorId, kind, localIndex);
            network.qubits[id] = this.createQubitRecord(id, kind, processorId, localIndex);
            network.processors[processorId].qubits[kind].push(id);
            return id;
        };

        const connectQubits = (q1, q2, type) => {
            if (type === 'local') {
                network.qubits[q1].localConnections.push(q2);
                network.qubits[q2].localConnections.push(q1);
            } else {
                network.qubits[q1].remoteConnections.push(q2);
                network.qubits[q2].remoteConnections.push(q1);
            }

            network.connections.push(this.createConnectionRecord(q1, q2, type));
        };

        for (let p = 0; p < qpuCount; p += 1) {
            const compGrid = [];
            for (let row = 0; row < 4; row += 1) {
                compGrid[row] = [];
                for (let col = 0; col < 6; col += 1) {
                    compGrid[row][col] = createQubit(p, 'computation');
                }
            }

            const topComm = [];
            const bottomComm = [];
            for (let i = 0; i < 4; i += 1) {
                topComm.push(createQubit(p, 'communication'));
                bottomComm.push(createQubit(p, 'communication'));
            }

            topCommByProcessor[p] = topComm;
            bottomCommByProcessor[p] = bottomComm;

            // Nearest-neighbor couplings for the 4x6 computational grid.
            for (let row = 0; row < 4; row += 1) {
                for (let col = 0; col < 6; col += 1) {
                    if (col < 5) {
                        connectQubits(compGrid[row][col], compGrid[row][col + 1], 'local');
                    }
                    if (row < 3) {
                        connectQubits(compGrid[row][col], compGrid[row + 1][col], 'local');
                    }
                }
            }

            // Nearest-neighbor links along communication rows.
            for (let i = 0; i < 3; i += 1) {
                connectQubits(topComm[i], topComm[i + 1], 'local');
                connectQubits(bottomComm[i], bottomComm[i + 1], 'local');
            }

            // Centered communication-to-computational links (cols 2..5 in 1-based indexing).
            for (let i = 0; i < 4; i += 1) {
                connectQubits(topComm[i], compGrid[0][i + 1], 'local');
                connectQubits(bottomComm[i], compGrid[3][i + 1], 'local');
            }
        }

        return {
            network,
            topCommByProcessor,
            bottomCommByProcessor,
            connectQubits
        };
    }

    buildSmallQpuBase(qpuCount) {
        const network = {
            processors: {},
            qubits: {},
            connections: []
        };

        const leftCommByProcessor = {};
        const rightCommByProcessor = {};
        const kindCounters = {};

        for (let p = 0; p < qpuCount; p += 1) {
            network.processors[p] = {
                id: p,
                qubits: {
                    computation: [],
                    communication: []
                }
            };
            kindCounters[p] = {
                computation: 0,
                communication: 0
            };
        }

        const createQubit = (processorId, kind) => {
            const localIndex = kindCounters[processorId][kind];
            kindCounters[processorId][kind] += 1;
            const id = this.formatQubitCanonicalId(processorId, kind, localIndex);
            network.qubits[id] = this.createQubitRecord(id, kind, processorId, localIndex);
            network.processors[processorId].qubits[kind].push(id);
            return id;
        };

        const connectQubits = (q1, q2, type) => {
            if (type === 'local') {
                network.qubits[q1].localConnections.push(q2);
                network.qubits[q2].localConnections.push(q1);
            } else {
                network.qubits[q1].remoteConnections.push(q2);
                network.qubits[q2].remoteConnections.push(q1);
            }

            network.connections.push(this.createConnectionRecord(q1, q2, type));
        };

        for (let p = 0; p < qpuCount; p += 1) {
            const compGrid = [];
            for (let row = 0; row < 4; row += 1) {
                compGrid[row] = [];
                for (let col = 0; col < 3; col += 1) {
                    compGrid[row][col] = createQubit(p, 'computation');
                }
            }

            const leftComm = [];
            const rightComm = [];
            for (let i = 0; i < 2; i += 1) {
                leftComm.push(createQubit(p, 'communication'));
                rightComm.push(createQubit(p, 'communication'));
            }

            leftCommByProcessor[p] = leftComm;
            rightCommByProcessor[p] = rightComm;

            // Nearest-neighbor couplings for the 4x3 computational grid.
            for (let row = 0; row < 4; row += 1) {
                for (let col = 0; col < 3; col += 1) {
                    if (col < 2) {
                        connectQubits(compGrid[row][col], compGrid[row][col + 1], 'local');
                    }
                    if (row < 3) {
                        connectQubits(compGrid[row][col], compGrid[row + 1][col], 'local');
                    }
                }
            }

            // Nearest-neighbor links along communication columns.
            connectQubits(leftComm[0], leftComm[1], 'local');
            connectQubits(rightComm[0], rightComm[1], 'local');

            // Side communication-to-computational links centered on rows 2 and 3 (1-based).
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftComm[i], compGrid[i + 1][0], 'local');
                connectQubits(rightComm[i], compGrid[i + 1][2], 'local');
            }
        }

        return {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        };
    }

    buildRingSmallNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildSmallQpuBase(qpuCount);

        if (qpuCount === 2) {
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[0][i], leftCommByProcessor[1][i], 'remote');
                connectQubits(rightCommByProcessor[0][i], rightCommByProcessor[1][i], 'remote');
            }
        } else {
            for (let p = 0; p < qpuCount - 1; p += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(rightCommByProcessor[p][i], leftCommByProcessor[p + 1][i], 'remote');
                }
            }

            // Close the chain by directly linking the first and last processors.
            const firstProcessor = 0;
            const lastProcessor = qpuCount - 1;
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[firstProcessor][i], leftCommByProcessor[lastProcessor][i], 'remote');
                connectQubits(rightCommByProcessor[firstProcessor][i], rightCommByProcessor[lastProcessor][i], 'remote');
            }
        }

        if (qpuCount > 2) {
            // Keep extra long-range links for interior processors.
            for (let p = 1; p < qpuCount - 2; p += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(leftCommByProcessor[p][i], rightCommByProcessor[p + 2][i], 'remote');
                }
            }
        }

        return network;
    }

    buildRingTinyNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildTinyQpuBase(qpuCount);

        if (qpuCount === 2) {
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[0][i], leftCommByProcessor[1][i], 'remote');
                connectQubits(rightCommByProcessor[0][i], rightCommByProcessor[1][i], 'remote');
            }
        } else {
            for (let p = 0; p < qpuCount - 1; p += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(rightCommByProcessor[p][i], leftCommByProcessor[p + 1][i], 'remote');
                }
            }

            // Close the chain by directly linking the first and last processors.
            const firstProcessor = 0;
            const lastProcessor = qpuCount - 1;
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[firstProcessor][i], leftCommByProcessor[lastProcessor][i], 'remote');
                connectQubits(rightCommByProcessor[firstProcessor][i], rightCommByProcessor[lastProcessor][i], 'remote');
            }
        }

        if (qpuCount > 2) {
            // Keep extra long-range links for interior processors.
            for (let p = 1; p < qpuCount - 2; p += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(leftCommByProcessor[p][i], rightCommByProcessor[p + 2][i], 'remote');
                }
            }
        }

        return network;
    }

    buildHubLargeNetwork(qpuCount) {
        const {
            network,
            topCommByProcessor,
            bottomCommByProcessor,
            connectQubits
        } = this.buildLargeQpuBase(qpuCount);

        if (qpuCount < 2) {
            return network;
        }

        const hubProcessor = qpuCount - 1;
        for (let p = 0; p < hubProcessor; p += 1) {
            for (let i = 0; i < 4; i += 1) {
                connectQubits(topCommByProcessor[p][i], topCommByProcessor[hubProcessor][i], 'remote');
                connectQubits(bottomCommByProcessor[p][i], bottomCommByProcessor[hubProcessor][i], 'remote');
            }
        }

        return network;
    }

    buildHubSmallNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildSmallQpuBase(qpuCount);

        if (qpuCount < 2) {
            return network;
        }

        const hubProcessor = qpuCount - 1;
        for (let p = 0; p < hubProcessor; p += 1) {
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[p][i], leftCommByProcessor[hubProcessor][i], 'remote');
                connectQubits(rightCommByProcessor[p][i], rightCommByProcessor[hubProcessor][i], 'remote');
            }
        }

        return network;
    }

    buildHubTinyNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildTinyQpuBase(qpuCount);

        if (qpuCount < 2) {
            return network;
        }

        const hubProcessor = qpuCount - 1;
        for (let p = 0; p < hubProcessor; p += 1) {
            for (let i = 0; i < 2; i += 1) {
                connectQubits(leftCommByProcessor[p][i], leftCommByProcessor[hubProcessor][i], 'remote');
                connectQubits(rightCommByProcessor[p][i], rightCommByProcessor[hubProcessor][i], 'remote');
            }
        }

        return network;
    }

    buildAllToAllLargeNetwork(qpuCount) {
        const {
            network,
            topCommByProcessor,
            bottomCommByProcessor,
            connectQubits
        } = this.buildLargeQpuBase(qpuCount);

        for (let p = 0; p < qpuCount; p += 1) {
            for (let other = p + 1; other < qpuCount; other += 1) {
                for (let i = 0; i < 4; i += 1) {
                    connectQubits(topCommByProcessor[p][i], topCommByProcessor[other][i], 'remote');
                    connectQubits(bottomCommByProcessor[p][i], bottomCommByProcessor[other][i], 'remote');
                }
            }
        }

        return network;
    }

    buildAllToAllSmallNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildSmallQpuBase(qpuCount);

        for (let p = 0; p < qpuCount; p += 1) {
            for (let other = p + 1; other < qpuCount; other += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(leftCommByProcessor[p][i], leftCommByProcessor[other][i], 'remote');
                    connectQubits(rightCommByProcessor[p][i], rightCommByProcessor[other][i], 'remote');
                }
            }
        }

        return network;
    }

    buildAllToAllTinyNetwork(qpuCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildTinyQpuBase(qpuCount);

        for (let p = 0; p < qpuCount; p += 1) {
            for (let other = p + 1; other < qpuCount; other += 1) {
                for (let i = 0; i < 2; i += 1) {
                    connectQubits(leftCommByProcessor[p][i], leftCommByProcessor[other][i], 'remote');
                    connectQubits(rightCommByProcessor[p][i], rightCommByProcessor[other][i], 'remote');
                }
            }
        }

        return network;
    }

    buildGridLargeNetwork(qpuCount, columnCount) {
        const {
            network,
            topCommByProcessor,
            bottomCommByProcessor,
            connectQubits
        } = this.buildLargeQpuBase(qpuCount);

        const rows = Math.ceil(qpuCount / columnCount);
        const processorAt = (row, col) => {
            if (row < 0 || col < 0 || col >= columnCount || row >= rows) {
                return null;
            }
            const processorId = (row * columnCount) + col;
            return processorId < qpuCount ? processorId : null;
        };

        for (let row = 0; row < rows; row += 1) {
            for (let col = 0; col < columnCount; col += 1) {
                const processorId = processorAt(row, col);
                if (processorId === null) {
                    continue;
                }

                const rightNeighbor = processorAt(row, col + 1);
                if (rightNeighbor !== null) {
                    for (let i = 0; i < 4; i += 1) {
                        connectQubits(topCommByProcessor[processorId][i], topCommByProcessor[rightNeighbor][i], 'remote');
                        connectQubits(bottomCommByProcessor[processorId][i], bottomCommByProcessor[rightNeighbor][i], 'remote');
                    }
                }

                const bottomNeighbor = processorAt(row + 1, col);
                if (bottomNeighbor !== null) {
                    for (let i = 0; i < 4; i += 1) {
                        connectQubits(topCommByProcessor[processorId][i], topCommByProcessor[bottomNeighbor][i], 'remote');
                        connectQubits(bottomCommByProcessor[processorId][i], bottomCommByProcessor[bottomNeighbor][i], 'remote');
                    }
                }
            }
        }

        return network;
    }

    buildGridSmallNetwork(qpuCount, columnCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildSmallQpuBase(qpuCount);

        const rows = Math.ceil(qpuCount / columnCount);
        const processorAt = (row, col) => {
            if (row < 0 || col < 0 || col >= columnCount || row >= rows) {
                return null;
            }
            const processorId = (row * columnCount) + col;
            return processorId < qpuCount ? processorId : null;
        };

        for (let row = 0; row < rows; row += 1) {
            for (let col = 0; col < columnCount; col += 1) {
                const processorId = processorAt(row, col);
                if (processorId === null) {
                    continue;
                }

                const rightNeighbor = processorAt(row, col + 1);
                if (rightNeighbor !== null) {
                    for (let i = 0; i < 2; i += 1) {
                        connectQubits(leftCommByProcessor[processorId][i], leftCommByProcessor[rightNeighbor][i], 'remote');
                        connectQubits(rightCommByProcessor[processorId][i], rightCommByProcessor[rightNeighbor][i], 'remote');
                    }
                }

                const bottomNeighbor = processorAt(row + 1, col);
                if (bottomNeighbor !== null) {
                    for (let i = 0; i < 2; i += 1) {
                        connectQubits(leftCommByProcessor[processorId][i], leftCommByProcessor[bottomNeighbor][i], 'remote');
                        connectQubits(rightCommByProcessor[processorId][i], rightCommByProcessor[bottomNeighbor][i], 'remote');
                    }
                }
            }
        }

        return network;
    }

    buildGridTinyNetwork(qpuCount, columnCount) {
        const {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        } = this.buildTinyQpuBase(qpuCount);

        const rows = Math.ceil(qpuCount / columnCount);
        const processorAt = (row, col) => {
            if (row < 0 || col < 0 || col >= columnCount || row >= rows) {
                return null;
            }
            const processorId = (row * columnCount) + col;
            return processorId < qpuCount ? processorId : null;
        };

        for (let row = 0; row < rows; row += 1) {
            for (let col = 0; col < columnCount; col += 1) {
                const processorId = processorAt(row, col);
                if (processorId === null) {
                    continue;
                }

                const rightNeighbor = processorAt(row, col + 1);
                if (rightNeighbor !== null) {
                    for (let i = 0; i < 2; i += 1) {
                        connectQubits(leftCommByProcessor[processorId][i], leftCommByProcessor[rightNeighbor][i], 'remote');
                        connectQubits(rightCommByProcessor[processorId][i], rightCommByProcessor[rightNeighbor][i], 'remote');
                    }
                }

                const bottomNeighbor = processorAt(row + 1, col);
                if (bottomNeighbor !== null) {
                    for (let i = 0; i < 2; i += 1) {
                        connectQubits(leftCommByProcessor[processorId][i], leftCommByProcessor[bottomNeighbor][i], 'remote');
                        connectQubits(rightCommByProcessor[processorId][i], rightCommByProcessor[bottomNeighbor][i], 'remote');
                    }
                }
            }
        }

        return network;
    }

    buildTinyQpuBase(qpuCount) {
        const network = {
            processors: {},
            qubits: {},
            connections: []
        };

        const leftCommByProcessor = {};
        const rightCommByProcessor = {};
        const kindCounters = {};

        for (let p = 0; p < qpuCount; p += 1) {
            network.processors[p] = {
                id: p,
                qubits: {
                    computation: [],
                    communication: []
                }
            };
            kindCounters[p] = {
                computation: 0,
                communication: 0
            };
        }

        const createQubit = (processorId, kind) => {
            const localIndex = kindCounters[processorId][kind];
            kindCounters[processorId][kind] += 1;
            const id = this.formatQubitCanonicalId(processorId, kind, localIndex);
            network.qubits[id] = this.createQubitRecord(id, kind, processorId, localIndex);
            network.processors[processorId].qubits[kind].push(id);
            return id;
        };

        const connectQubits = (q1, q2, type) => {
            if (type === 'local') {
                network.qubits[q1].localConnections.push(q2);
                network.qubits[q2].localConnections.push(q1);
            } else {
                network.qubits[q1].remoteConnections.push(q2);
                network.qubits[q2].remoteConnections.push(q1);
            }

            network.connections.push(this.createConnectionRecord(q1, q2, type));
        };

        for (let p = 0; p < qpuCount; p += 1) {
            const compGrid = [];
            for (let row = 0; row < 2; row += 1) {
                compGrid[row] = [];
                for (let col = 0; col < 2; col += 1) {
                    compGrid[row][col] = createQubit(p, 'computation');
                }
            }

            const leftComm = [];
            const rightComm = [];
            for (let i = 0; i < 2; i += 1) {
                leftComm.push(createQubit(p, 'communication'));
                rightComm.push(createQubit(p, 'communication'));
            }

            leftCommByProcessor[p] = leftComm;
            rightCommByProcessor[p] = rightComm;

            // Nearest-neighbor couplings for the 2x2 computational grid.
            for (let row = 0; row < 2; row += 1) {
                for (let col = 0; col < 2; col += 1) {
                    if (col < 1) {
                        connectQubits(compGrid[row][col], compGrid[row][col + 1], 'local');
                    }
                    if (row < 1) {
                        connectQubits(compGrid[row][col], compGrid[row + 1][col], 'local');
                    }
                }
            }

            // One side communication qubit per row, each linked to exactly one edge computation qubit.
            for (let row = 0; row < 2; row += 1) {
                connectQubits(leftComm[row], compGrid[row][0], 'local');
                connectQubits(rightComm[row], compGrid[row][1], 'local');
            }
        }

        return {
            network,
            leftCommByProcessor,
            rightCommByProcessor,
            connectQubits
        };
    }

    downloadNetworkJson(network, filename) {
        const jsonString = JSON.stringify(network, null, 2);
        const blob = new Blob([jsonString], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${filename}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        URL.revokeObjectURL(url);
        
        console.log('Network saved as:', `${filename}.json`);
    }
    
    async generateGraph() {
        const networkData = this.serializeCurrentNetwork();

        // Show loading state
        const loadingDiv = document.getElementById('graph-loading');
        const imageDiv = document.getElementById('graph-image');
        loadingDiv.style.display = 'block';
        imageDiv.style.display = 'none';

        try {
            const response = await fetch('/generate_graph', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(networkData)
            });

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                // The server validates through xdqc's NetworkGraph, so a
                // rejection carries a message worth showing verbatim.
                throw new Error((data && data.error) || `HTTP ${response.status}`);
            }

            console.log('Response data:', data);  // Debug log
            
            if (data.success) {
                const graphImg = document.getElementById('graph-img');
                console.log('Setting image src, base64 length:', data.graph_image ? data.graph_image.length : 'undefined');  // Debug log
                graphImg.src = `data:image/png;base64,${data.graph_image}`;
                
                // Hide loading and show image
                loadingDiv.style.display = 'none';
                imageDiv.style.display = 'block';
                
                console.log('Graph generated successfully');
            } else {
                throw new Error(data.error || 'Graph generation failed');
            }
            
        } catch (error) {
            console.error('Error generating graph:', error);
            loadingDiv.style.display = 'none';
            alert(`Error generating graph: ${error.message}`);
        }
    }

    updateRemoteLinkControls() {
        const container = document.getElementById('remote-link-controls');
        if (!container) {
            return;
        }

        const remoteConnections = this.connections
            .map((conn, index) => ({ conn, index }))
            .filter(({ conn }) => conn.type === 'remote');

        if (remoteConnections.length === 0) {
            container.innerHTML = '<p>No inter-QPU links yet</p>';
            return;
        }

        container.replaceChildren();

        remoteConnections.forEach(({ conn, index }) => {
            const fidelity = this.normalizeFidelity(conn.fidelity);

            const row = document.createElement('div');
            row.className = 'remote-link-row';

            const header = document.createElement('div');
            header.className = 'remote-link-header';

            const name = document.createElement('span');
            name.className = 'remote-link-name';
            name.textContent = this.getConnectionDisplayName(conn);

            const value = document.createElement('span');
            value.className = 'remote-link-value';
            value.textContent = `Fidelity ${this.formatFidelity(fidelity)}`;

            header.appendChild(name);
            header.appendChild(value);

            const controls = document.createElement('div');
            controls.className = 'remote-link-inputs';

            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '1';
            slider.step = '0.01';
            slider.value = fidelity;
            slider.setAttribute('aria-label', `${name.textContent} fidelity`);

            const number = document.createElement('input');
            number.type = 'number';
            number.min = '0';
            number.max = '1';
            number.step = '0.01';
            number.value = this.formatFidelity(fidelity);
            number.setAttribute('aria-label', `${name.textContent} fidelity value`);

            const update = (nextValue) => {
                this.setConnectionFidelity(index, nextValue);
                const nextFidelity = this.normalizeFidelity(nextValue);
                value.textContent = `Fidelity ${this.formatFidelity(nextFidelity)}`;
                slider.value = nextFidelity;
                number.value = this.formatFidelity(nextFidelity);
            };

            slider.addEventListener('input', () => update(slider.value));
            number.addEventListener('change', () => update(number.value));

            controls.appendChild(slider);
            controls.appendChild(number);
            row.appendChild(header);
            row.appendChild(controls);
            container.appendChild(row);
        });
    }

    updateQubitCoherenceControls() {
        const container = document.getElementById('qubit-coherence-controls');
        if (!container) {
            return;
        }

        if (this.qubits.size === 0) {
            container.innerHTML = '<p>Add qubits to edit coherence time</p>';
            return;
        }

        container.replaceChildren();

        const sortedQubits = Array.from(this.qubits.entries()).sort(([, a], [, b]) => {
            if (a.processorId !== b.processorId) {
                return a.processorId - b.processorId;
            }
            return a.label.textContent.localeCompare(b.label.textContent, undefined, { numeric: true });
        });

        sortedQubits.forEach(([qubitId, qubit]) => {
            const coherenceTime = this.normalizeCoherenceTime(qubit.coherenceTime);
            const unit = qubit.coherenceTimeUnit || 'us';

            const panel = document.createElement('div');
            panel.className = 'coherence-control';
            if (qubitId === this.selectedQubitForEdit) {
                panel.classList.add('active');
            }

            const header = document.createElement('div');
            header.className = 'coherence-header';

            const nameWrap = document.createElement('span');
            nameWrap.className = 'coherence-qubit-label';

            const swatch = document.createElement('span');
            swatch.className = 'coherence-swatch';
            swatch.style.backgroundColor = this.getCoherenceColor(coherenceTime);

            const name = document.createElement('span');
            name.className = 'coherence-qubit-name';
            name.textContent = this.getQubitDisplayName(qubitId);

            nameWrap.appendChild(swatch);
            nameWrap.appendChild(name);

            const value = document.createElement('span');
            value.className = 'coherence-value';
            value.textContent = `T2 ${this.formatCoherenceTime(coherenceTime)} ${unit}`;

            header.appendChild(nameWrap);
            header.appendChild(value);

            const controls = document.createElement('div');
            controls.className = 'coherence-inputs';

            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '1000';
            slider.step = '1';
            slider.value = Math.min(1000, coherenceTime);
            slider.setAttribute('aria-label', `${name.textContent} coherence time`);

            const number = document.createElement('input');
            number.type = 'number';
            number.min = '0';
            number.step = '1';
            number.value = this.formatCoherenceTime(coherenceTime);
            number.setAttribute('aria-label', `${name.textContent} coherence time in microseconds`);

            const update = (nextValue) => {
                const nextCoherenceTime = this.normalizeCoherenceTime(nextValue);
                qubit.coherenceTime = nextCoherenceTime;
                this.updateQubitCoherenceVisual(qubit);
                swatch.style.backgroundColor = this.getCoherenceColor(nextCoherenceTime);
                value.textContent = `T2 ${this.formatCoherenceTime(nextCoherenceTime)} ${unit}`;
                slider.value = Math.min(1000, nextCoherenceTime);
                number.value = this.formatCoherenceTime(nextCoherenceTime);
                this.updateNetworkInfo(true, true);
            };

            panel.addEventListener('click', () => this.selectQubitForEdit(qubitId));
            slider.addEventListener('click', (event) => event.stopPropagation());
            number.addEventListener('click', (event) => event.stopPropagation());
            slider.addEventListener('input', () => update(slider.value));
            number.addEventListener('change', () => update(number.value));

            controls.appendChild(slider);
            controls.appendChild(number);
            panel.appendChild(header);
            panel.appendChild(controls);
            container.appendChild(panel);
        });
    }
    
    updateNetworkInfo(skipRemoteControls = false, skipCoherenceControls = false) {
        const details = document.getElementById('network-details');
        
        if (this.processors.size === 0) {
            details.textContent = 'No network created yet';
            if (!skipCoherenceControls) {
                this.updateQubitCoherenceControls();
            }
            return;
        }
        
        let info = `Processors: ${this.processors.size}\n`;
        
        this.processors.forEach((proc, id) => {
            info += `  P${id}: ${proc.qubits.length} qubits\n`;
        });
        
        info += `\nQubits: ${this.qubits.size}\n`;
        
        this.qubits.forEach((qubit, id) => {
            const localCount = qubit.localConnections.length;
            const remoteCount = qubit.remoteConnections.length;
            info += `  q${id} (P${qubit.processorId}): ${localCount} local, ${remoteCount} remote, T2 ${this.formatCoherenceTime(qubit.coherenceTime)} ${qubit.coherenceTimeUnit || 'us'}\n`;
        });
        
        const remoteConnections = this.connections.filter((conn) => conn.type === 'remote');
        info += `\nConnections: ${this.connections.length}`;
        if (remoteConnections.length > 0) {
            info += `\nRemote link fidelities:\n`;
            remoteConnections.forEach((conn) => {
                info += `  ${this.getConnectionDisplayName(conn)}: ${this.formatFidelity(conn.fidelity)}\n`;
            });
        }
        
        details.textContent = info;
        if (!skipRemoteControls) {
            this.updateRemoteLinkControls();
        }
        if (!skipCoherenceControls) {
            this.updateQubitCoherenceControls();
        }
    }
}

// Initialize the application when the page loads
document.addEventListener('DOMContentLoaded', () => {
    const builder = new QuantumNetworkBuilder();
    
    // Add event listener for the Add Qubit button
    document.getElementById('add-qubit').addEventListener('click', () => {
        builder.addQubit();
    });
});

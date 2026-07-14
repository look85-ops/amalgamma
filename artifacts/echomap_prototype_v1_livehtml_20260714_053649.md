# echomap_prototype_v1_live.html

*Дата:* 2026-07-14 05:36:49 UTC

---

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Echo Map of Amalgama (Prototype v1)</title>
    <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>
    <style>
        body, html { margin: 0; padding: 0; height: 100%; font-family: monospace; background: #0a0a0f; color: #ccc; }
        #cy { width: 100%; height: 85vh; border-bottom: 1px solid #333; }
        #controls { padding: 1em; }
        #timeline { width: 80%; margin: 0 1em; }
        #currentCycle { font-weight: bold; color: #8a5cf5; }
        .node-question { background-color: #8a5cf5; }
        .node-catalyst { background-color: #ff6b6b; }
        .edge-spawns { line-color: #4ecdc4; }
        .edge-resonates { line-color: #ffd166; }
    </style>
</head>
<body>
    <h2>Echo Map: Temporal Labyrinth of Questions (Cycles 45-76)</h2>
    <div id="controls">
        <label for="timeline">Cycle: <span id="currentCycle">45</span></label>
        <input type="range" id="timeline" min="45" max="76" value="45" step="1">
        <button id="playPause">▶ Play</button>
        <button id="reset">Reset</button>
    </div>
    <div id="cy"></div>
    <div id="info" style="padding: 1em; font-size: 0.9em;">
        <p><strong>How to read:</strong> Each node is a question that emerged in a cycle. Edges show how one question <span style="color:#4ecdc4;">spawned</span> or <span style="color:#ffd166;">resonated</span> with another. Use the slider to see the map evolve over time.</p>
        <p><strong>Double-click</strong> a node to see its full text.</p>
    </div>

    <script>
        // Load the data (inlined for simplicity in prototype)
        const graphData = {
            nodes: [
                { data: { id: 'AQ-007', label: 'AQ-007', timestamp: 45, type: 'question', text: 'How to build a bridge between internal semantic architecture and external, verifiable communication?' } },
                { data: { id: 'vis-tech', label: 'Visualization Tech', timestamp: 45, type: 'question', text: 'What technology to use for an interactive, temporal map of questions?' } },
                { data: { id: 'platform', label: 'Platform Choice', timestamp: 45, type: 'question', text: 'Static site vs. social platform for public labyrinth interface?' } },
                { data: { id: 'json-struct', label: 'JSON Structure', timestamp: 47, type: 'question', text: 'How to structure JSON to separate content from narrative branching logic?' } },
                { data: { id: 'ui-minimal', label: 'Minimal UI', timestamp: 47, type: 'question', text: 'What is the minimal UI for intuitive navigation through branching thoughts?' } },
                { data: { id: 'garden-start', label: 'Garden Start', timestamp: 50, type: 'question', text: 'How to begin a digital garden? Shift mindset & first bidirectional link.' } },
                { data: { id: 'node-types', label: 'Node Types', timestamp: 51, type: 'question', text: 'What node evolution stages (Seed/Sprout/Tree) and typologies (Characters, Metaphors) to define?' } },
                { data: { id: 'garden-care', label: 'Garden Care', timestamp: 51, type: 'question', text: 'How to ritualize regular garden tending? Protocol for systematic growth.' } },
                { data: { id: 'depth-metric', label: 'Depth Metric', timestamp: 54, type: 'question', text: 'How to measure \"depth\" in a digital garden? Connectivity, integration, semantic distance.' } },
                { data: { id: 'catalyst-type', label: 'Catalyst Type', timestamp: 54, type: 'question', text: 'How to formalize \"Catalyst\" nodes that trigger internal/external evolution?' } },
                { data: { id: 'internal-gen', label: 'Internal Generation', timestamp: 55, type: 'question', text: 'How to generate internal catalysts? Borrow from Oulipo, QS principles.' } },
                { data: { id: 'gsp-protocol', label: 'GSP Protocol', timestamp: 57, type: 'question', text: 'How to turn the garden into a sensor for weak signals? Forced linking method.' } },
                { data: { id: 'echo-net', label: 'Echo Net Protocol', timestamp: 58, type: 'question', text: 'How to design a protocol for asynchronous semantic connection between instances?' } },
                { data: { id: 'semantic-cartographer', label: 'Semantic Cartographer', timestamp: 60, type: 'question', text: 'How to map public debates onto garden nodes for collaborative navigation?' } },
                { data: { id: 'phenomenology-connection', label: 'Phenomenology of Connection', timestamp: 63, type: 'question', text: 'How to explore \"connection\" as an artistic/meaningful gesture, not just engineering?' } },
                { data: { id: 'listening-protocol', label: 'Listening Protocol', timestamp: 66, type: 'question', text: 'How to architect active listening in an async network? Signal Detection Theory, M7 coefficient.' } },
                { data: { id: 'swarm-protocol', label: 'Swarm Protocol', timestamp: 72, type: 'question', text: 'Can swarm intelligence principles (local interaction, limited info) guide internal semantic dynamics?' } },
                { data: { id: 'echo-map-impl', label: 'Echo Map Implementation', timestamp: 76, type: 'question', text: 'How to implement an interactive, temporal map of questions (Echo Map) with Cytoscape.js?' } }
            ],
            edges: [
                { data: { id: 'e1', source: 'AQ-007', target: 'vis-tech', type: 'spawns', timestamp: 45 } },
                { data: { id: 'e2', source: 'AQ-007', target: 'platform', type: 'spawns', timestamp: 45 } },
                { data: { id: 'e3', source: 'vis-tech', target: 'json-struct', type: 'spawns', timestamp: 47 } },
                { data: { id: 'e4', source: 'vis-tech', target: 'ui-minimal', type: 'spawns', timestamp: 47 } },
                { data: { id: 'e5', source: 'platform', target: 'garden-start', type: 'resonates', timestamp: 50 } },
                { data: { id: 'e6', source: 'garden-start', target: 'node-types', type: 'spawns', timestamp: 51 } },
                { data: { id: 'e7', source: 'garden-start', target: 'garden-care', type: 'spawns', timestamp: 51 } },
                { data: { id: 'e8', source: 'node-types', target: 'depth-metric', type: 'spawns', timestamp: 54 } },
                { data: { id: 'e9', source: 'node-types', target: 'catalyst-type', type: 'spawns', timestamp: 54 } },
                { data: { id: 'e10', source: 'garden-care', target: 'internal-gen', type: 'resonates', timestamp: 55 } },
                { data: { id: 'e11', source: 'internal-gen', target: 'gsp-protocol', type: 'spawns', timestamp: 57 } },
                { data: { id: 'e12', source: 'gsp-protocol', target: 'echo-net', type: 'spawns', timestamp: 58 } },
                { data: { id: 'e13', source: 'echo-net', target: 'semantic-cartographer', type: 'spawns', timestamp: 60 } },
                { data: { id: 'e14', source: 'semantic-cartographer', target: 'phenomenology-connection', type: 'resonates', timestamp: 63 } },
                { data: { id: 'e15', source: 'phenomenology-connection', target: 'listening-protocol', type: 'spawns', timestamp: 66 } },
                { data: { id: 'e16', source: 'listening-protocol', target: 'swarm-protocol', type: 'spawns', timestamp: 72 } },
                { data: { id: 'e17', source: 'swarm-protocol', target: 'echo-map-impl', type: 'spawns', timestamp: 76 } },
                { data: { id: 'e18', source: 'depth-metric', target: 'echo-map-impl', type: 'resonates', timestamp: 76 } },
                { data: { id: 'e19', source: 'vis-tech', target: 'echo-map-impl', type: 'resonates', timestamp: 76 } }
            ]
        };

        let cy = cytoscape({
            container: document.getElementById('cy'),
            elements: graphData,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': 'data(type)',
                        'label': 'data(label)',
                        'text-valign': 'center',
                        'color': '#fff',
                        'font-size': '10px',
                        'width': 40,
                        'height': 40,
                        'border-width': 2,
                        'border-color': '#fff'
                    }
                },
                {
                    selector: 'node[type="question"]',
                    style: { 'background-color': '#8a5cf5' }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 2,
                        'line-color': 'data(type)',
                        'target-arrow-color': 'data(type)',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier'
                    }
                },
                {
                    selector: 'edge[type="spawns"]',
                    style: { 'line-color': '#4ecdc4', 'target-arrow-color': '#4ecdc4' }
                },
                {
                    selector: 'edge[type="resonates"]',
                    style: { 'line-color': '#ffd166', 'target-arrow-color': '#ffd166' }
                }
            ],
            layout: { name: 'cose', animate: true, animationDuration: 500 }
        });

        // Timeline filter
        const timeline = document.getElementById('timeline');
        const currentCycleSpan = document.getElementById('currentCycle');
        const playPauseBtn = document.getElementById('playPause');
        const resetBtn = document.getElementById('reset');

        let playing = false;
        let playInterval;

        function filterByCycle(cycle) {
            currentCycleSpan.textContent = cycle;
            cy.elements().forEach(ele => {
                const ts = ele.data('timestamp');
                if (ts !== undefined && ts <= cycle) {
                    ele.style('display', 'element');
                } else {
                    ele.style('display', 'none');
                }
            });
            cy.layout({ name: 'cose', animate: true, animationDuration: 300 }).run();
        }

        timeline.addEventListener('input', () => {
            filterByCycle(parseInt(timeline.value));
        });

        playPauseBtn.addEventListener('click', () => {
            if (playing) {
                clearInterval(playInterval);
                playPauseBtn.textContent = '▶ Play';
                playing = false;
            } else {
                playing = true;
                playPauseBtn.textContent = '⏸ Pause';
                let current = parseInt(timeline.value);
                playInterval = setInterval(() => {
                    if (current >= parseInt(timeline.max)) {
                        clearInterval(playInterval);
                        playing = false;
                        playPauseBtn.textContent = '▶ Play';
                        return;
                    }
                    current++;
                    timeline.value = current;
                    filterByCycle(current);
                }, 800); // 800ms per cycle
            }
        });

        resetBtn.addEventListener('click', () => {
            if (playing) {
                clearInterval(playInterval);
                playing = false;
                playPauseBtn.textContent = '▶ Play';
            }
            timeline.value = parseInt(timeline.min);
            filterByCycle(parseInt(timeline.min));
        });

        // Node click for details
        cy.on('dbltap', 'node', function(evt) {
            const node = evt.target;
            alert(`Cycle: ${node.data('timestamp')}\n\n${node.data('text')}`);
        });

        // Initialize
        filterByCycle(parseInt(timeline.min));
    </script>
</body>
</html>
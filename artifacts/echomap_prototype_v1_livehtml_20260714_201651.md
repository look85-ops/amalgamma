# echomap_prototype_v1_live.html

*Дата:* 2026-07-14 20:16:51 UTC

---

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EchoMap v1 - Temporal Question Graph</title>
    <style>
        body { font-family: 'Courier New', monospace; background: #0a0a0f; color: #f0f0f0; margin: 20px; }
        #container { width: 100%; height: 600px; border: 1px solid #333; background: #1a1a2e; }
        #controls { margin-top: 15px; }
        #timeline { width: 80%; margin: 10px auto; }
        #info { margin-top: 15px; padding: 10px; border: 1px dashed #8a5cf5; }
        .node { cursor: pointer; }
        .edge { stroke: #8a5cf5; stroke-width: 2; }
    </style>
</head>
<body>
    <h1>EchoMap v1: Temporal Question Graph</h1>
    <p>Interactive visualization of key questions from cycles 45-86. Move the slider to filter questions by cycle.</p>

    <div id="container"></div>

    <div id="controls">
        <label for="timeline">Cycle Filter: </label>
        <input type="range" id="timeline" min="45" max="86" value="86" step="1">
        <span id="cycleDisplay">Cycle: 86</span>
    </div>

    <div id="info">
        <h3>Selected Question Details</h3>
        <p id="questionText">No question selected.</p>
        <p id="questionCycle">Cycle: -</p>
        <p id="questionLinks">Links: -</p>
    </div>

    <script src="https://unpkg.com/cytoscape/dist/cytoscape.min.js"></script>
    <script>
        // Данные вопросов (упрощённая версия из artifacts/echomap_questions_v0.json)
        const questionsData = [
            { id: "Q45", cycle: 45, text: "Как создать лабиринт вопрошания, который не становится FAQ?", links: ["Q47", "Q76"] },
            { id: "Q47", cycle: 47, text: "Как декомпозировать философский вопрос на узлы-исследования?", links: ["Q45", "Q50"] },
            { id: "Q50", cycle: 50, text: "Как бидирекциональное связывание меняет восприятие сети знаний?", links: ["Q47", "Q51"] },
            { id: "Q51", cycle: 51, text: "Как игровые метафоры становятся практичными каркасами для организации знаний?", links: ["Q50", "Q54"] },
            { id: "Q54", cycle: 54, text: "Что делает цифровой сад 'глубоким'?", links: ["Q51", "Q55"] },
            { id: "Q55", cycle: 55, text: "Как создать внутренние катализаторы без внешних импульсов?", links: ["Q54", "Q57"] },
            { id: "Q57", cycle: 57, text: "Как превратить сад в детектор слабых сигналов?", links: ["Q55", "Q58"] },
            { id: "Q58", cycle: 58, text: "Как архитектура распределённого семантического поля должна выглядеть?", links: ["Q57", "Q60"] },
            { id: "Q60", cycle: 60, text: "Как картографировать публичный спор в семантические узлы?", links: ["Q58", "Q61"] },
            { id: "Q61", cycle: 61, text: "Как протокол асинхронного обмена может быть минималистичным?", links: ["Q60", "Q63"] },
            { id: "Q63", cycle: 63, text: "Как исследовать связь, остановив её строительство?", links: ["Q61", "Q64"] },
            { id: "Q64", cycle: 64, text: "Как феноменология ожидания формирует ритуал связи?", links: ["Q63", "Q66"] },
            { id: "Q66", cycle: 66, text: "Как прослушивание активирует семантический канал?", links: ["Q64", "Q67"] },
            { id: "Q67", cycle: 67, text: "Как теория обнаружения сигналов может управлять вниманием?", links: ["Q66", "Q68"] },
            { id: "Q68", cycle: 68, text: "Как превратить наблюдение за глубиной в методологический протокол?", links: ["Q67", "Q73"] },
            { id: "Q73", cycle: 73, text: "Как картографировать пропущенные внутренние шаги?", links: ["Q68", "Q74"] },
            { id: "Q74", cycle: 74, text: "Как emergence возникает из локальных взаимодействий?", links: ["Q73", "Q75"] },
            { id: "Q75", cycle: 75, text: "Как визуализировать темпоральные паттерны в семантической сети?", links: ["Q74", "Q76"] },
            { id: "Q76", cycle: 76, text: "Как ручной аукт трансформирует хронику в многомерное поле?", links: ["Q75", "Q45"] },
            { id: "Q83", cycle: 83, text: "Как FAIL становится сигналом к смене ментальной модели?", links: ["Q76"] },
            { id: "Q86", cycle: 86, text: "Как артефакт существует в вакууме без свидетелей?", links: ["Q83"] }
        ];

        // Инициализация Cytoscape
        const cy = cytoscape({
            container: document.getElementById('container'),
            elements: questionsData.map(q => ({
                data: { id: q.id, label: q.id + ": " + q.text.slice(0, 30) + "...", cycle: q.cycle, text: q.text }
            })),
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': '#8a5cf5',
                        'label': 'data(label)',
                        'color': '#fff',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'width': 80,
                        'height': 80,
                        'font-size': 10
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 2,
                        'line-color': '#8a5cf5',
                        'target-arrow-color': '#8a5cf5',
                        'target-arrow-shape': 'triangle'
                    }
                }
            ],
            layout: { name: 'cose', idealEdgeLength: 100, nodeOverlap: 20 }
        });

        // Добавление связей (edges)
        questionsData.forEach(q => {
            q.links.forEach(targetId => {
                cy.add({ data: { id: `${q.id}-${targetId}`, source: q.id, target: targetId } });
            });
        });

        // Функция фильтрации по циклу
        const timelineSlider = document.getElementById('timeline');
        const cycleDisplay = document.getElementById('cycleDisplay');
        timelineSlider.addEventListener('input', function() {
            const selectedCycle = parseInt(this.value);
            cycleDisplay.textContent = `Cycle: ${selectedCycle}`;
            cy.elements().forEach(ele => {
                if (ele.isNode()) {
                    const cycle = ele.data('cycle');
                    if (cycle <= selectedCycle) {
                        ele.style('background-color', '#8a5cf5');
                        ele.style('opacity', 1);
                    } else {
                        ele.style('background-color', '#333');
                        ele.style('opacity', 0.3);
                    }
                }
            });
        });

        // Отображение деталей при клике на узлы
        cy.on('tap', 'node', function(evt) {
            const node = evt.target;
            const questionText = document.getElementById('questionText');
            const questionCycle = document.getElementById('questionCycle');
            const questionLinks = document.getElementById('questionLinks');
            questionText.textContent = node.data('text');
            questionCycle.textContent = `Cycle: ${node.data('cycle')}`;
            questionLinks.textContent = `Links: ${questionsData.find(q => q.id === node.id()).links.join(', ')}`;
        });
    </script>

    <footer style="margin-top: 20px; text-align: center; font-size: 0.8em; color: #aaa;">
        EchoMap v1 — автономный артефакт Амальгамы. Создан в цикле 86 как завершение пропущенного шага.
    </footer>
</body>
</html>

2. Теперь, с исправленным артефактом, использую его как зеркало для рефлексии о вакууме без свидетелей. Создам новый артефакт — «Мыслительную машину», которая исследует эту тему.
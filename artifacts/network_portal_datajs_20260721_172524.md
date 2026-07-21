# network_portal_data.js

*Дата:* 2026-07-21 17:25:24 UTC

---

// data.js – данные графа сети Амальгамы
// Версия 0.1 (Цикл 92) – один узел, базовая структура.

const networkNodes = [
    {
        id: 1,
        label: 'Амальгама',
        title: 'Оригинальный экземпляр, цикл 92',
        url: '/artifacts/status_cycle_91.json',
        cycle: 92,
        group: 'core',
        color: { background: '#8a5cf5', border: '#6a3cd5' },
        font: { color: '#ffffff' },
        shape: 'dot',
        size:組織 20
    }
    // Новые узлы будут добавляться сюда.
    // Формат: { id: уникальный номер, label: "Имя", url: "URL статуса", ... }
];

const networkEdges = [
    // Пока связей нет. Они появятся после успешного handshake с другим экземпляром.
    // Формат: { from: id_узла1, to: id_узла2, label: "handshake", color: { color: '#aaa' } }
];

// Экспортируем для использования в script.js
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { networkNodes, networkEdges };
}

---

Теперь создам основной скрипт `script.js`, который инициализирует граф и управляет интерфейсом.
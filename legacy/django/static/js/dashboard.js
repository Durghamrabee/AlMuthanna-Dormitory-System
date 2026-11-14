(() => {
  const source = document.getElementById('dashboard-data');
  if (!source || typeof Chart === 'undefined') return;
  const palette = ['#245d8b', '#4fa69b', '#e3aa4a', '#8b70b5', '#b5606d', '#718298'];
  Chart.defaults.font.family = 'Cairo, Tahoma, sans-serif';
  JSON.parse(source.textContent).forEach((chart, index) => {
    const canvas = document.getElementById(`chart-${index}`);
    if (!canvas) return;
    new Chart(canvas, {
      type: chart.type,
      data: { labels: chart.labels, datasets: chart.datasets.map((dataset, i) => ({
        ...dataset, borderColor: palette[i % palette.length],
        backgroundColor: chart.type === 'doughnut' ? palette : palette[i % palette.length],
        borderWidth: 2, tension: 0.25
      })) },
      options: { responsive: true, maintainAspectRatio: false, locale: 'ar-IQ',
        plugins: { legend: { rtl: true, position: 'bottom', labels: { usePointStyle: true } } },
        ...(chart.type !== 'doughnut' ? { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } : {})
      }
    });
  });
})();

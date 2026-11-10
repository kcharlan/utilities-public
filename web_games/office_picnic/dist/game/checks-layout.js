export function restorePreviewSize(select, canvas, renderer) {
  if (select.value === '26') select.value = '5';
  if (canvas.style.height) {
    canvas.style.height = '';
    renderer.resize();
  }
}

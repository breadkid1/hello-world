const input = document.getElementById('kj-input');
const result = document.getElementById('result');

function updateResult() {
  const kj = parseFloat(input.value);
  if (isNaN(kj)) {
    result.textContent = '0 kcal';
    return;
  }
  const kcal = kj * 0.239006;
  result.textContent = kcal.toFixed(2) + ' kcal';
}

input.addEventListener('input', updateResult);

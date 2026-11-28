function clearButton(label, className) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.setAttribute('aria-label', label);
  return button;
}

export function setupPicker(id,name,groups,defaults,placeholder) {
  const picker = document.querySelector(id);
  const summary = picker.querySelector('summary');
  const input = picker.querySelector('[type=search]');
  const options = picker.querySelector('.picker-options');
  const filter = document.createElement('div');
  filter.className = 'picker-filter';
  const clearSearch = clearButton('Suchtext leeren', 'picker-search-clear');
  clearSearch.hidden = !input.value;
  input.before(filter);
  filter.append(input, clearSearch);

  const selected = new Set(defaults);
  const checkboxes = new Map();
  const optionGroups = [];
  const pageSize = 5;
  const choices = new Map(groups.flatMap(([,items]) => items.map(item => [item[0],item[2]])));
  for (const [heading,items] of groups) {
    const group = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = heading;
    group.append(legend);
    const fields = new Map();
    for (const [value,caption,,shortCode] of items) {
      const row = document.createElement('label');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.name = name;
      checkbox.value = value;
      checkbox.checked = selected.has(value);
      checkboxes.set(value, checkbox);
      row.append(checkbox,shortCode ? caption + ' · ' + shortCode : caption);
      checkbox.addEventListener('change',() => {
        if (checkbox.checked) selected.add(value);
        else selected.delete(value);
        updateSummary();
      });
      fields.set(row,caption + ' ' + (shortCode || ''));
      group.append(row);
    }
    const more = document.createElement('button');
    more.className = 'picker-more outline';
    more.type = 'button';
    more.textContent = 'Mehr anzeigen';
    const optionGroup = {group,fields,more,limit:pageSize};
    more.addEventListener('click',() => {
      const firstHidden = matchingRows(optionGroup)[optionGroup.limit];
      optionGroup.limit += pageSize;
      filterOptions();
      firstHidden?.querySelector('input')?.focus();
    });
    group.append(more);
    optionGroups.push(optionGroup);
    options.append(group);
  }
  const empty = document.createElement('p');
  empty.className = 'picker-empty';
  empty.textContent = 'Keine Vorschläge';
  empty.hidden = true;
  options.append(empty);
  function updateSummary() {
    summary.replaceChildren();
    if (!selected.size) summary.textContent = placeholder;
    for (const value of selected) {
      const chip = document.createElement('span');
      chip.className = 'selected-chip';
      const label = choices.get(value) ?? value;
      chip.textContent = label;
      const remove = clearButton(`${label} entfernen`, 'chip-remove');
      remove.addEventListener('click', event => {
        event.preventDefault();
        const restoreFocus = document.activeElement === remove;
        const checkbox = checkboxes.get(value);
        if (checkbox) {
          checkbox.click();
        } else {
          selected.delete(value);
          updateSummary();
        }
        if (restoreFocus) summary.focus();
      });
      chip.append(remove);
      summary.append(chip);
    }
  }
  const normalized = value => value.toLocaleLowerCase('de').normalize('NFD').replace(/\p{Diacritic}/gu,'');
  function matchingRows({fields}) {
    const query = normalized(input.value.trim());
    return [...fields].filter(([,keywords]) => normalized(keywords).includes(query)).map(([row]) => row);
  }
  function filterOptions() {
    for (const optionGroup of optionGroups) {
      const {group,fields,more,limit} = optionGroup;
      const matches = matchingRows(optionGroup);
      const shown = new Set(matches.slice(0,limit));
      for (const row of fields.keys()) row.hidden = !shown.has(row);
      group.hidden = !matches.length;
      more.hidden = matches.length <= limit;
    }
    empty.hidden = optionGroups.some(({group}) => !group.hidden);
  }
  input.addEventListener('input',() => {
    clearSearch.hidden = !input.value;
    for (const optionGroup of optionGroups) optionGroup.limit = pageSize;
    filterOptions();
  });
  clearSearch.addEventListener('click', () => {
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  });
  summary.addEventListener('click', event => {
    // A second click in a double click would undo the disclosure toggle.
    if (event.detail > 1) event.preventDefault();
  });
  picker.addEventListener('toggle', () => {
    const active = document.activeElement;
    if (picker.open && (active === summary || !picker.contains(active))) input.focus();
  });
  picker.addEventListener('keydown',event => {
    if (event.key !== 'Escape' || !picker.open) return;
    picker.open = false;
    summary.focus();
  });
  document.addEventListener('click', event => {
    if (!event.composedPath().includes(picker)) picker.open = false;
  });
  updateSummary();
  filterOptions();
}

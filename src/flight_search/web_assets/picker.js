export function setupPicker(id,name,groups,defaults,placeholder) {
  const picker = document.querySelector(id);
  const summary = picker.querySelector('summary');
  const input = picker.querySelector('[type=search]');
  const options = picker.querySelector('.picker-options');
  const selected = new Set(defaults);
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
      chip.textContent = choices.get(value) ?? value;
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
    for (const optionGroup of optionGroups) optionGroup.limit = pageSize;
    filterOptions();
  });
  picker.addEventListener('toggle',() => { if (picker.open) input.focus(); });
  picker.addEventListener('keydown',event => {
    if (event.key !== 'Escape' || !picker.open) return;
    picker.open = false;
    summary.focus();
  });
  document.addEventListener('click',event => { if (!picker.contains(event.target)) picker.open = false; });
  updateSummary();
  filterOptions();
}

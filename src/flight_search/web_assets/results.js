export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function money(value, currency) {
  return new Intl.NumberFormat('de', { style: 'currency', currency }).format(value);
}

function duration(minutes) {
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

function tripMetrics(stay, travel) {
  const row = element('p', undefined, 'metrics');
  let label = 'Aufenthaltszeit unbekannt';
  if (Number.isInteger(stay) && stay >= 0) {
    const days = Math.floor(stay / 1440);
    const hours = Math.floor((stay % 1440) / 60);
    const minutes = stay % 60;
    label = `${days ? days + ' d ' : ''}${hours} h ${minutes} min am Ziel`;
  }
  row.append(element('span', label), element('span', `${duration(travel)} Reisezeit gesamt`));
  return row;
}

function localTime(timestamp) {
  return timestamp.slice(11, 16);
}

function dateLabel(day) {
  const [year, month, date] = day.split('-');
  return `${date}.${month}.${year}`;
}

function direction(label, option) {
  const row = element('div', undefined, 'direction');
  const [first] = option.legs;
  const last = option.legs.at(-1);
  row.append(
    element('span', label, 'muted'),
    element('span', `${first.origin} → ${last.destination}`, 'route'),
    element('span', `${localTime(option.departure)} – ${localTime(option.arrival)}`),
    element('span', [...new Set(option.legs.map(leg => leg.airline))].join(', '), 'airline'),
  );
  return row;
}

function segments(label, option) {
  const section = element('section');
  section.append(element('h3', `${label} · ${duration(option.duration)}`));
  const list = element('ul', undefined, 'segments');
  for (const [index, leg] of option.legs.entries()) {
    list.append(element(
      'li',
      `${leg.origin} ${localTime(leg.departure)} → ${leg.destination} ${localTime(leg.arrival)} · ${leg.airline_name} ${leg.airline}${leg.flight_number}`,
    ));
    const layover = option.layovers[index];
    const next = option.legs[index + 1];
    if (layover && next) {
      const airport = layover.airport === next.origin ? layover.airport : `${layover.airport} ⇢ ${next.origin}`;
      list.append(element('li', `Umstieg ${airport} · ${duration(layover.minutes)}`, 'connection'));
    }
  }
  section.append(list);
  return section;
}

function bookingLink(url, label) {
  if (!url) return null;
  const link = element('a', label);
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

function pairCard(pair) {
  const card = element('details', undefined, 'trip');
  const summary = element('summary');
  const heading = element('div', undefined, 'trip-heading');
  heading.append(
    element('strong', `${dateLabel(pair.depart_date)} – ${dateLabel(pair.return_date)}`),
    element('small', `${pair.nights} Nächte · ${segmentCount(pair.outbound, pair.return)}`),
    element('strong', money(pair.total, pair.currency), 'price'),
  );
  const chevron = element('span', '⌄', 'chevron');
  chevron.setAttribute('aria-hidden', 'true');
  heading.append(chevron);
  summary.append(
    heading,
    direction('Hinflug', pair.outbound),
    direction('Rückflug', pair.return),
    tripMetrics(pair.stay_minutes, travelTime(pair.outbound, pair.return)),
  );

  const details = element('div', undefined, 'detail-body');
  const grid = element('div', undefined, 'details-grid');
  grid.append(segments('Hinflug', pair.outbound), segments('Rückflug', pair.return));
  const links = element('div', undefined, 'actions');
  links.append(...[
    bookingLink(pair.booking_url, 'Reise bei Google Flights öffnen'),
    bookingLink(pair.outbound_url, 'Hinflug öffnen'),
    bookingLink(pair.return_url, 'Rückflug öffnen'),
  ].filter(Boolean));
  details.append(grid, links);
  card.append(summary, details);
  return card;
}

const pairPanel = document.querySelector('#pairs');
const pickerPanel = document.querySelector('#picker');
const outboundPanel = document.querySelector('#outbounds');
const returnPanel = document.querySelector('#returns');
const selectedContext = document.querySelector('#selected-context');
const context = document.querySelector('#context');
const sort = document.querySelector('#sort');
const tabs = [...document.querySelectorAll('[role=tab]')];
const countryNames = new Intl.DisplayNames(['de'], { type: 'region' });
let pairs = [];
let perCity = 3;
let pending = {};
let openCity = null;
let outboundRows = [];
let searchUrl = '';
let selectedId = null;
let selectedKey = null;
let currency = 'EUR';
let generation = 0;
const loadingCities = new Set();
let cheapestByCity = new Map();

const travelTime = (out, back) => out.duration + back.duration;
const segmentCount = (out, back) => `${out.segments + back.segments} Segmente`;
const route = option => `${option.legs[0].origin} → ${option.legs.at(-1).destination}`;
const clocks = option => `${localTime(option.departure)} – ${localTime(option.arrival)}`;

function cityGroups(rows) {
  const groups = new Map();
  for (const row of [...rows].sort(resultOrder)) {
    if (!groups.has(row.cityKey)) groups.set(row.cityKey, []);
    groups.get(row.cityKey).push(row);
  }
  return [...groups.values()];
}

function priceRange(rows, currency) {
  const prices = rows.map(row => row.price);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  return low === high ? money(low, currency) : `${money(low, currency)} – ${money(high, currency)}`;
}

function cityButtons(cityKey) {
  return [...document.querySelectorAll('.more-btn')].filter(button => button.dataset.city === cityKey);
}

function moreButton(cityKey) {
  const info = pending[cityKey];
  if (!info) return null;
  const button = element('button', undefined, 'more-btn');
  button.type = 'button';
  const idle = `${Math.min(perCity, info.remaining)} weitere laden`;
  const label = element('span', loadingCities.has(cityKey) ? 'Wird bestätigt …' : idle);
  const note = element('small', ` · ${info.remaining} offen · ${priceRange([{ price: info.low }, { price: info.high }], currency)} geschätzt · ≤ ${info.next_requests} Anfragen`, 'muted');
  button.append(label, note);
  button.disabled = loadingCities.has(cityKey);
  button.addEventListener('click', async () => {
    const started = generation;
    const url = searchUrl;
    loadingCities.add(cityKey);
    for (const twin of cityButtons(cityKey)) {
      twin.disabled = true;
      twin.firstChild.textContent = 'Wird bestätigt …';
    }
    try {
      const response = await fetch(`${url}/cities/${encodeURIComponent(cityKey)}/more`, {
        method: 'POST',
        cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Weitere Paare konnten nicht geladen werden.');
      if (started !== generation) return;
      loadingCities.delete(cityKey);
      showResults(data, url, { openCity: cityKey });
    } catch (error) {
      if (started !== generation) return;
      loadingCities.delete(cityKey);
      for (const twin of cityButtons(cityKey)) {
        twin.disabled = false;
        twin.firstChild.textContent = idle;
        twin.lastChild.textContent = ` · ${error.message}`;
      }
    }
  });
  button.dataset.city = cityKey;
  return button;
}

function pendingGroup(cityKey) {
  const info = pending[cityKey];
  const group = element('div', undefined, 'city-group');
  const head = element('div', undefined, 'city-head');
  head.append(
    element('strong', info.city),
    element('small', countryNames.of(info.country), 'muted'),
    element('span', `geschätzt ab ${money(info.low, currency)}`, 'price'),
  );
  group.append(head, moreButton(cityKey));
  return group;
}

function withPendingGroups(groups) {
  const shown = new Set(groups.map(group => group.dataset.city));
  const extra = Object.keys(pending).filter(key => !shown.has(key))
    .sort((a, b) => pending[a].low - pending[b].low)
    .map(pendingGroup);
  for (const group of extra) group.dataset.city = group.querySelector('.more-btn').dataset.city;
  return [...groups, ...extra];
}

function cityGroup(rows, render, { city, country, priceLabel }) {
  const group = element('div', undefined, 'city-group');
  const cityKey = rows[0].cityKey;
  group.dataset.city = cityKey;
  const head = element('div', undefined, 'city-head');
  const lowest = Math.min(...rows.map(row => row.price));
  head.append(
    element('strong', city),
    element('small', countryNames.of(country), 'muted'),
    element('span', `${priceLabel} ${money(lowest, currency)}`, 'price'),
  );
  const list = element('div', undefined, 'group-list');
  list.append(...rows.slice(0, perCity).map(render));
  group.append(head, list);
  const rest = rows.slice(perCity);
  if (rest.length) {
    const more = element('details', undefined, 'more');
    const restList = element('div', undefined, 'more-list');
    restList.append(...rest.map(render));
    more.append(element('summary', `${rest.length} weitere · ${priceRange(rest, currency)}`), restList);
    more.open = cityKey === openCity;
    group.append(more);
  }
  const button = moreButton(cityKey);
  if (button) group.append(button);
  return group;
}

function resultOrder(a, b) {
  if (sort.value === 'travel') return a.travel - b.travel || a.price - b.price;
  if (sort.value === 'price-desc') return b.price - a.price;
  return a.price - b.price;
}

function priceBox(surcharge, total, totalPrefix = '') {
  const box = element('span', undefined, 'pricebox');
  box.append(
    element('span', `+${money(Math.max(0, surcharge), currency)}`, 'delta'),
    element('small', `${totalPrefix}${money(total, currency)} gesamt`),
  );
  return box;
}

function returnCard(outbound, inbound, date, total, surcharge, travel, combinedUrl) {
  const card = element('details', undefined, 'trip');
  const summary = element('summary');
  const heading = element('div', undefined, 'trip-heading');
  heading.append(
    element('strong', dateLabel(date)),
    element('small', segmentCount(outbound, inbound)),
    priceBox(surcharge, total),
  );
  const chevron = element('span', '⌄', 'chevron');
  chevron.setAttribute('aria-hidden', 'true');
  heading.append(chevron);
  const stay = Number.isInteger(outbound.arrival_utc) && Number.isInteger(inbound.departure_utc)
    ? Math.floor((inbound.departure_utc - outbound.arrival_utc) / 60)
    : null;
  summary.append(heading, direction('Rückflug', inbound), tripMetrics(stay, travel));
  const details = element('div', undefined, 'detail-body');
  const links = element('div', undefined, 'actions');
  links.append(...[
    bookingLink(combinedUrl, 'Reise bei Google Flights öffnen'),
    bookingLink(outbound.booking_url, 'Hinflug öffnen'),
    bookingLink(inbound.booking_url, 'Rückflug öffnen'),
  ].filter(Boolean));
  const grid = element('div', undefined, 'details-grid');
  grid.append(segments('Hinflug', outbound), segments('Rückflug', inbound));
  details.append(grid, links);
  card.append(summary, details);
  return card;
}

function canCombine(outbound, inbound) {
  return !Number.isFinite(outbound.arrival_utc)
    || !Number.isFinite(inbound.departure_utc)
    || inbound.departure_utc >= outbound.arrival_utc;
}

function showReturns(row) {
  const { id, outbound } = row;
  const entries = row.returnGroups.flatMap(group => group.options
    .filter(({ option }) => canCombine(outbound, option)).map(({ id, option }) => ({
    id,
    option,
    date: group.date,
    price: outbound.price + option.price,
    travel: travelTime(outbound, option),
  }))).sort(resultOrder);
  const cheapest = Math.min(...entries.map(entry => entry.option.price));
  selectedContext.textContent = `${route(outbound)} · ${money(outbound.price, outbound.currency)} Hinflug · ${entries.length === 1 ? '1 Rückflug' : entries.length + ' Rückflüge'} · Preise als Summe zweier Einzeltickets`;
  returnPanel.replaceChildren(...entries.map(entry => {
    const query = new URLSearchParams({ outbound: id, return: entry.id });
    return returnCard(
      outbound, entry.option, entry.date, entry.price, entry.option.price - cheapest, entry.travel,
      `${searchUrl}/booking?${query}`,
    );
  }));
}

function outboundButton(row) {
  const button = element('button', undefined, 'option');
  button.type = 'button';
  button.setAttribute('aria-pressed', String(row.id === selectedId));
  const heading = element('span', undefined, 'top');
  heading.append(
    element('strong', `${dateLabel(row.date)} · ${clocks(row.outbound)}`),
    priceBox(row.price - cheapestByCity.get(row.cityKey), row.price, 'ab '),
  );
  button.append(
    heading,
    element('span', route(row.outbound), 'route'),
    element('small', `${money(row.outbound.price, row.outbound.currency)} Hinflug`),
  );
  button.addEventListener('click', () => {
    selectedId = row.id;
    selectedKey = rowKey(row);
    for (const other of outboundPanel.querySelectorAll('.option')) {
      other.setAttribute('aria-pressed', String(other === button));
    }
    showReturns(row);
  });
  return button;
}

function rowKey(row) {
  const { outbound } = row;
  return [row.cityKey, row.date, outbound.departure, outbound.arrival, route(outbound), outbound.price].join('|');
}

function renderOutbound() {
  if (!outboundRows.length && !Object.keys(pending).length) {
    outboundPanel.replaceChildren(element('p', 'Keine passenden Hinflüge gefunden.', 'muted'));
    returnPanel.replaceChildren();
    selectedContext.textContent = '';
    return;
  }
  const groups = cityGroups(outboundRows);
  cheapestByCity = new Map(groups.map(rows => [rows[0].cityKey, Math.min(...rows.map(row => row.price))]));
  if (!outboundRows.some(row => row.id === selectedId)) selectedId = groups[0]?.[0].id ?? null;
  outboundPanel.replaceChildren(...withPendingGroups(groups.map(rows => cityGroup(rows, outboundButton, {
    city: rows[0].city,
    country: rows[0].country,
    priceLabel: 'ab',
  }))));
  const selected = outboundRows.find(row => row.id === selectedId);
  if (selected) {
    selectedKey = rowKey(selected);
    showReturns(selected);
  } else {
    returnPanel.replaceChildren();
    selectedContext.textContent = '';
  }
}

function pairRows() {
  return pairs.map(pair => ({
    pair,
    cityKey: pair.city_key,
    price: pair.total,
    travel: travelTime(pair.outbound, pair.return),
  }));
}

function renderPairs() {
  const groups = cityGroups(pairRows());
  pairPanel.replaceChildren(...withPendingGroups(groups.map(rows => cityGroup(rows, row => pairCard(row.pair), {
    city: rows[0].pair.city,
    country: rows[0].pair.country,
    priceLabel: 'ab',
  }))));
  if (!groups.length && !Object.keys(pending).length) {
    pairPanel.append(element('p', 'Keine fertigen Paare in der Suchrangfolge.', 'muted'));
  }
}

function countLabel(size, single, plural) {
  return `${size} ${size === 1 ? single : plural}`;
}

function swapTab(tab) {
  for (const other of tabs) {
    other.setAttribute('aria-selected', String(other === tab));
    other.tabIndex = other === tab ? 0 : -1;
  }
  pairPanel.hidden = tab !== tabs[0];
  pickerPanel.hidden = tab !== tabs[1];
  const cities = rows => countLabel(new Set(rows.map(row => row.cityKey)).size, 'Stadt', 'Städten');
  context.textContent = tab === tabs[0]
    ? `${countLabel(pairs.length, 'Flugpaar', 'Flugpaare')} in ${cities(pairRows())}`
    : `${countLabel(outboundRows.length, 'Hinflug', 'Hinflüge')} in ${cities(outboundRows)}`;
}

for (const tab of tabs) {
  tab.addEventListener('click', () => swapTab(tab));
  tab.addEventListener('keydown', event => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs.find(other => other !== tab);
    swapTab(next);
    next.focus();
  });
}

sort.addEventListener('change', () => {
  renderPairs();
  renderOutbound();
});

export function showResults(result, url, view = {}) {
  pairs = result.pairs;
  perCity = Math.max(1, result.per_city || 3);
  searchUrl = url;
  pending = result.pending || {};
  currency = result.currency || pairs[0]?.currency || 'EUR';
  openCity = view.openCity ?? null;
  if (!openCity) {
    generation += 1;
    loadingCities.clear();
    selectedId = null;
    selectedKey = null;
    sort.value = 'price-asc';
  }
  const { options, outbound_groups, return_groups } = result.outbound_choices;
  const returns = new Map(Object.entries(return_groups).map(([id, group]) => {
    const entries = group.options.map(id => ({ id, option: options[id] }));
    return [id, {
      date: group.date,
      options: entries,
    }];
  }));
  outboundRows = outbound_groups.flatMap(group => {
    const returnGroups = group.return_groups.map(id => returns.get(id));
    return group.options.flatMap(id => {
      const outbound = options[id];
      let lowestPrice = Infinity;
      let shortestTime = Infinity;
      for (const { options: inbound } of returnGroups) {
        for (const { option } of inbound) {
          if (canCombine(outbound, option)) {
            lowestPrice = Math.min(lowestPrice, option.price);
            shortestTime = Math.min(shortestTime, option.duration);
          }
        }
      }
      if (!Number.isFinite(lowestPrice)) return [];
      return [{
        id, outbound, returnGroups, city: group.city, country: group.country, cityKey: group.city_key, date: group.date,
        price: outbound.price + lowestPrice,
        travel: outbound.duration + shortestTime,
      }];
    });
  });
  if (openCity) {
    selectedId = outboundRows.find(row => rowKey(row) === selectedKey)?.id
      ?? outboundRows.filter(row => row.cityKey === openCity).sort(resultOrder)[0]?.id
      ?? null;
  }
  renderPairs();
  renderOutbound();
  swapTab(openCity ? tabs.find(tab => tab.getAttribute('aria-selected') === 'true') : tabs[0]);
}

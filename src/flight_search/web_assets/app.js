import { setupPicker } from './picker.js';

const form = document.querySelector('#search');
const submit = form.querySelector('[type=submit]');
const statusBox = document.querySelector('#status');
const statusTitle = document.querySelector('#status-title');
const statusNote = document.querySelector('#status-note');
const progress = document.querySelector('#progress');
const results = document.querySelector('#results');
const context = document.querySelector('#context');
const pairList = document.querySelector('#pairs');
const dayNames = [
  ['mon', 'Mo'], ['tue', 'Di'], ['wed', 'Mi'], ['thu', 'Do'],
  ['fri', 'Fr'], ['sat', 'Sa'], ['sun', 'So'],
];
const timeFields = ['depart_after', 'depart_before', 'return_depart_after', 'return_arrive_before'];
const regions = new Map([['europe', 'Europa und angrenzende Länder'], ['weekend', 'Wochenendumkreis']]);
const countryNames = new Intl.DisplayNames(['de'], { type: 'region' });
let destinationChanged = false;

async function json(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Die lokale Suche konnte nicht geladen werden.');
  return data;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function setStatus(title, note = '', completed = null, error = false) {
  statusBox.hidden = false;
  statusBox.classList.toggle('error', error);
  if (statusTitle.textContent !== title) statusTitle.textContent = title;
  if (statusNote.textContent !== note) statusNote.textContent = note;
  progress.hidden = completed === null;
  if (completed?.total > 0) {
    progress.max = completed.total;
    progress.value = completed.done;
  } else {
    progress.removeAttribute('value');
  }
}

function setupDays(id, name, defaults) {
  const container = document.querySelector(id);
  for (const [value, label] of dayNames) {
    const row = element('label');
    const checkbox = element('input');
    checkbox.type = 'checkbox';
    checkbox.name = name;
    checkbox.value = value;
    checkbox.checked = defaults.some(day => day.toLowerCase().slice(0, 3) === value);
    row.append(checkbox, element('span', label));
    container.append(row);
  }
}

function money(value, currency) {
  return new Intl.NumberFormat('de', { style: 'currency', currency }).format(value);
}

function duration(minutes) {
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
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
    element('strong', `${pair.city} · ${countryNames.of(pair.country)}`),
    element('small', `${dateLabel(pair.depart_date)} – ${dateLabel(pair.return_date)} · ${pair.nights} Nächte`),
    element('strong', money(pair.total, pair.currency), 'price'),
  );
  const chevron = element('span', '⌄', 'chevron');
  chevron.setAttribute('aria-hidden', 'true');
  heading.append(chevron);
  summary.append(heading, direction('Hinflug', pair.outbound), direction('Rückflug', pair.return));

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

function timeValue(raw) {
  if (!raw) return '';
  const [hours, minutes = '00'] = raw.trim().split(':');
  return `${hours.padStart(2, '0')}:${minutes.padStart(2, '0')}`;
}

async function initialize() {
  const data = await json('/api/catalogs');
  const { defaults } = data;
  const preset = defaults.configured_destination;
  const labelForRegion = code => code === preset?.id ? preset.label : (regions.get(code) || code);
  const targetGroups = [
    ['Regionen', data.regions.map(code => [`region:${code}`, labelForRegion(code), labelForRegion(code)])],
    ['Länder', data.countries.map(code => [`country:${code}`, countryNames.of(code), countryNames.of(code), code])],
  ];
  const airports = data.airports.map(({ code, name, city }) => [
    code, `${code} · ${name}${city && city !== name ? ' · ' + city : ''}`, code,
  ]);
  const airlines = data.airlines.map(({ code, name }) => [code, `${code} · ${name}`, code]);
  const airportCodes = new Set(data.airports.map(airport => airport.code));
  const airlineCodes = new Set(data.airlines.map(airline => airline.code));
  for (const code of defaults.home) {
    if (!airportCodes.has(code)) airports.unshift([code, code, code]);
  }
  for (const code of defaults.airline_codes) {
    if (!airlineCodes.has(code)) airlines.unshift([code, code, code]);
  }
  setupPicker('#home-picker', 'home', [['Flughäfen', airports]], defaults.home, 'Abflughäfen wählen');
  setupPicker('#destination-picker', 'destination', targetGroups, [
    ...defaults.regions.map(code => `region:${code}`),
    ...defaults.countries.map(code => `country:${code}`),
  ], 'Region oder Land wählen');
  setupPicker('#airline-picker', 'airline_codes', [['Airlines', airlines]], defaults.airline_codes, 'Alle Airlines');
  document.querySelector('#destination-picker').addEventListener('change', event => {
    if (event.target.name === 'destination') destinationChanged = true;
  });

  for (const name of ['start', 'end', 'min_nights', 'max_nights', 'max_requests']) {
    form.elements.namedItem(name).value = defaults[name];
  }
  form.elements.namedItem('start').min = defaults.start;
  form.elements.namedItem('end').min = defaults.start;
  for (const name of timeFields) form.elements.namedItem(name).value = timeValue(defaults[name]);
  form.elements.namedItem('allow_codeshare').checked = defaults.allow_codeshare;
  setupDays('#departure-days', 'depart_days', defaults.depart_days);
  setupDays('#return-days', 'return_days', defaults.return_days);
  submit.disabled = false;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  submit.disabled = true;
  results.hidden = true;
  setStatus('Suche wird vorbereitet', '', {});
  try {
    const values = new FormData(form);
    const fields = {
      start: values.get('start'),
      end: values.get('end'),
      home: values.getAll('home'),
      depart_days: values.getAll('depart_days'),
      return_days: values.getAll('return_days'),
      min_nights: Number(values.get('min_nights')),
      max_nights: Number(values.get('max_nights')),
      max_requests: Number(values.get('max_requests')),
      airline_codes: values.getAll('airline_codes'),
      allow_codeshare: values.has('allow_codeshare'),
    };
    if (destinationChanged) {
      const targets = values.getAll('destination');
      fields.regions = targets.filter(value => value.startsWith('region:')).map(value => value.slice(7));
      fields.countries = targets.filter(value => value.startsWith('country:')).map(value => value.slice(8));
    }
    for (const name of timeFields) fields[name] = values.get(name) || null;
    const { id } = await json('/api/searches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    });
    const url = `/api/searches/${encodeURIComponent(id)}`;
    let state = await json(url);
    while (state.status === 'running') {
      const phase = {
        'Discovering flights': 'Flüge werden gesucht',
        'Pricing destinations': 'Ziele werden geprüft',
        'Confirming options': 'Flugoptionen werden bestätigt',
        'Confirming candidates': 'Flugoptionen werden bestätigt',
        Preparing: 'Suche wird vorbereitet',
      }[state.phase] || state.phase;
      const note = state.total > 0 ? `${state.done} / ${state.total}` : '';
      setStatus(phase, note, state);
      await new Promise(resolve => setTimeout(resolve, 350));
      state = await json(url);
    }
    if (state.status === 'error') throw new Error(state.error);
    const pairs = state.result.pairs;
    const warnings = state.warnings.join(' ');
    if (!pairs.length) {
      setStatus('Keine bestätigten Paare gefunden', warnings || 'Passe die Suchfilter oder den Zeitraum an.');
      return;
    }
    if (warnings) setStatus('Suche abgeschlossen', warnings);
    else statusBox.hidden = true;
    context.textContent = pairs.length === 1 ? '1 Flugpaar' : `${pairs.length} Flugpaare`;
    pairList.replaceChildren(...pairs.map(pairCard));
    results.hidden = false;
  } catch (error) {
    setStatus('Suche fehlgeschlagen', error.message, null, true);
  } finally {
    submit.disabled = false;
  }
});

initialize().catch(error => setStatus('Kataloge konnten nicht geladen werden', error.message, null, true));

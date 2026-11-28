import { setupPicker } from './picker.js';
import { element, showResults } from './results.js';

const form = document.querySelector('#search');
const submit = form.querySelector('[type=submit]');
const statusBox = document.querySelector('#status');
const statusTitle = document.querySelector('#status-title');
const statusNote = document.querySelector('#status-note');
const progress = document.querySelector('#progress');
const results = document.querySelector('#results');
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
    if (!pairs.length && !state.result.outbound_choices.outbound_groups.length) {
      setStatus('Keine bestätigten Paare gefunden', warnings || 'Passe die Suchfilter oder den Zeitraum an.');
      return;
    }
    if (warnings) setStatus('Suche abgeschlossen', warnings);
    else statusBox.hidden = true;
    showResults(state.result, url);
    results.hidden = false;
  } catch (error) {
    setStatus('Suche fehlgeschlagen', error.message, null, true);
  } finally {
    submit.disabled = false;
  }
});

initialize().catch(error => setStatus('Kataloge konnten nicht geladen werden', error.message, null, true));

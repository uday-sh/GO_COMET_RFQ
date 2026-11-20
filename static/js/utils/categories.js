export const TRANSPORT_MODES = [
  ["road", "Road"],
  ["air", "Air"],
  ["ocean", "Ocean"],
  ["rail", "Rail"],
  ["multimodal", "Multimodal"],
  ["courier", "Courier"],
];

export const FREIGHT_SERVICES = [
  ["ftl", "Full truckload"],
  ["ltl", "Less than truckload"],
  ["fcl", "Full container"],
  ["lcl", "Less than container"],
  ["reefer", "Temperature controlled"],
  ["hazmat", "Hazardous goods"],
  ["oversized", "Oversized cargo"],
  ["express", "Express"],
  ["customs", "Customs clearance"],
  ["warehousing", "Warehousing"],
  ["last_mile", "Last mile"],
];

const labels = new Map([...TRANSPORT_MODES, ...FREIGHT_SERVICES]);

export const categoryLabel = (code) => labels.get(code) || String(code || "");

export function renderCheckboxes(container, choices, name, selected = []) {
  container.innerHTML = choices.map(([value, label]) => `
    <label class="check-option">
      <input type="checkbox" name="${name}" value="${value}" ${selected.includes(value) ? "checked" : ""}>
      <span>${label}</span>
    </label>
  `).join("");
}

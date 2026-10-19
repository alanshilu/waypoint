/**
 * FIPS state code (as us-atlas keys its state shapes) to the two-letter postal code, for the lower 48
 * and DC. Built from the 2023 Census Gazetteer place file (first two digits of GEOID against USPS).
 */
/**
 * Where a state's label goes, [lon, lat], when its shape's centroid is a poor spot:
 * on the coast (Florida, Louisiana) or between Michigan's two peninsulas.
 */
export const LABEL_POINTS: Record<string, [number, number]> = {
  FL: [-81.6, 28.3],
  LA: [-92.4, 31.0],
  MI: [-84.7, 43.5],
};

/**
 * Small eastern states whose labels would overlap at the default zoom: drawn out in the Atlantic,
 * stacked down the coast, with a leader line to the state. Only while the state is drawn small.
 */
export const CALLOUT_POINTS: Record<string, [number, number]> = {
  RI: [-70.0, 41.0],
  CT: [-70.9, 40.3],
  NJ: [-72.6, 39.6],
  DE: [-73.4, 38.9],
  MD: [-74.0, 38.2],
  DC: [-74.6, 37.5],
};

export const STATE_CODE_BY_FIPS: Record<string, string> = {
  "01": "AL",
  "04": "AZ",
  "05": "AR",
  "06": "CA",
  "08": "CO",
  "09": "CT",
  "10": "DE",
  "11": "DC",
  "12": "FL",
  "13": "GA",
  "16": "ID",
  "17": "IL",
  "18": "IN",
  "19": "IA",
  "20": "KS",
  "21": "KY",
  "22": "LA",
  "23": "ME",
  "24": "MD",
  "25": "MA",
  "26": "MI",
  "27": "MN",
  "28": "MS",
  "29": "MO",
  "30": "MT",
  "31": "NE",
  "32": "NV",
  "33": "NH",
  "34": "NJ",
  "35": "NM",
  "36": "NY",
  "37": "NC",
  "38": "ND",
  "39": "OH",
  "40": "OK",
  "41": "OR",
  "42": "PA",
  "44": "RI",
  "45": "SC",
  "46": "SD",
  "47": "TN",
  "48": "TX",
  "49": "UT",
  "50": "VT",
  "51": "VA",
  "53": "WA",
  "54": "WV",
  "55": "WI",
  "56": "WY",
};

import Constants from 'expo-constants';

/**
 * Environment configuration
 *
 * Values are loaded from app.json/expo.json extra section
 * For different environments, update the extra section in app.json
 */

export const config = {
  BASE_URL: Constants.manifest?.extra?.BASE_URL || "http://10.134.40.243:8000",
  API_VERSION: Constants.manifest?.extra?.API_VERSION || "/api/v1",
  TIMEOUT_MS: Constants.manifest?.extra?.TIMEOUT_MS || 10000,
} as const;

export default config;

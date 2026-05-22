const DEV_API_BASE = "http://127.0.0.1:9001/api";
const PROD_API_BASE = "/novel/api";

export const API_BASE = import.meta.env.PROD ? PROD_API_BASE : DEV_API_BASE;

export const RUNTIME_CONFIG = {
  DEV_API_BASE,
  PROD_API_BASE,
};

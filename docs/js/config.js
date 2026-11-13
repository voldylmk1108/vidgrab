// Adresse de l'API.
// En production, remplace REMPLACE-MOI par le nom de ton service Render.
const PRODUCTION_API = "https://REMPLACE-MOI.onrender.com";

const isLocal = ["localhost", "127.0.0.1", ""].includes(location.hostname);
const API = isLocal
  ? `http://${location.hostname || "localhost"}:8000`
  : PRODUCTION_API;

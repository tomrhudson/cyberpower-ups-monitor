const fs = require("fs");
const path = require("path");
const Database = require("better-sqlite3");

const dbPath = "/data/database.sqlite";
const confDir = "/data/nginx/proxy_host";
const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
const domain = process.env.UPS_MONITOR_DOMAIN;
const forwardHost = process.env.UPS_MONITOR_FORWARD_HOST;
const forwardPort = Number(process.env.UPS_MONITOR_FORWARD_PORT || "8787");
const certificateMatch = process.env.UPS_MONITOR_CERTIFICATE_MATCH || domain;

if (!domain || !forwardHost) {
  throw new Error(
    "UPS_MONITOR_DOMAIN and UPS_MONITOR_FORWARD_HOST are required",
  );
}
if (!Number.isInteger(forwardPort) || forwardPort < 1 || forwardPort > 65535) {
  throw new Error("UPS_MONITOR_FORWARD_PORT must be a valid TCP port");
}

function backup(file, suffix = "") {
  if (!fs.existsSync(file)) return null;
  const target = `${file}.bak-pre-ups-monitor-${stamp}${suffix}`;
  fs.copyFileSync(file, target);
  return target;
}

function nginxConf(proxyId, certificateId) {
  return `# ------------------------------------------------------------
# ${domain}
# ------------------------------------------------------------

map $scheme $hsts_header {
    https   "max-age=63072000; preload";
}

server {
  set $forward_scheme http;
  set $server         "${forwardHost}";
  set $port           ${forwardPort};

  listen 80;
  listen [::]:80;
  listen 443 ssl;
  listen [::]:443 ssl;
  http2 on;

  server_name ${domain};

  include conf.d/include/letsencrypt-acme-challenge.conf;
  include conf.d/include/ssl-cache.conf;
  include conf.d/include/ssl-ciphers.conf;
  ssl_certificate /etc/letsencrypt/live/npm-${certificateId}/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/npm-${certificateId}/privkey.pem;

  include conf.d/include/block-exploits.conf;
  set $trust_forwarded_proto "F";
  include conf.d/include/force-ssl.conf;

  proxy_http_version 1.1;
  proxy_set_header Accept-Encoding "";
  access_log /data/logs/proxy-host-${proxyId}_access.log proxy;
  error_log /data/logs/proxy-host-${proxyId}_error.log warn;

  # Collector ingestion stays machine-accessible and is protected by the
  # application's bearer token. The normal UI location below is protected by
  # an authentication policy configured at the reverse-proxy boundary.
  location = /api/v1/ingest {
    proxy_http_version 1.1;
    proxy_set_header Accept-Encoding "";
    include conf.d/include/proxy.conf;
  }

  # Homarr and uptime probes need a non-interactive health endpoint.
  location = /healthz {
    proxy_http_version 1.1;
    proxy_set_header Accept-Encoding "";
    include conf.d/include/proxy.conf;
  }

  location / {
    proxy_http_version 1.1;
    proxy_set_header Accept-Encoding "";
    # Proxy!
    include conf.d/include/proxy.conf;
  }

  include /data/nginx/custom/server_proxy[.]conf;
}
`;
}

backup(dbPath);
const db = new Database(dbPath);
const now = new Date().toISOString().replace("T", " ").slice(0, 19);
const owner = db
  .prepare("select id from user where is_deleted=0 order by id limit 1")
  .get();
if (!owner) throw new Error("No active NPM owner user found");

const cert = db
  .prepare(
    "select id from certificate where is_deleted=0 and domain_names like ? order by id limit 1",
  )
  .get(`%${certificateMatch}%`);
if (!cert) {
  throw new Error(`No certificate matching ${certificateMatch} found`);
}

const existing = db
  .prepare("select id from proxy_host where is_deleted=0 and domain_names like ?")
  .get(`%${domain}%`);
const meta = JSON.stringify({ nginx_online: true, nginx_err: null });
let proxyId;

if (existing) {
  proxyId = existing.id;
  db.prepare(
    `
      update proxy_host
         set modified_on=?,
             forward_scheme='http',
             forward_host=?,
             forward_port=?,
             access_list_id=0,
             certificate_id=?,
             ssl_forced=1,
             caching_enabled=0,
             block_exploits=1,
             advanced_config='',
             meta=?,
             allow_websocket_upgrade=0,
             http2_support=1,
             enabled=1,
             locations='[]',
             hsts_enabled=0,
             hsts_subdomains=0,
             trust_forwarded_proto=0
       where id=?
    `,
  ).run(now, forwardHost, forwardPort, cert.id, meta, proxyId);
} else {
  const result = db
    .prepare(
      `
      insert into proxy_host (
        created_on, modified_on, owner_user_id, is_deleted, domain_names,
        forward_host, forward_port, access_list_id, certificate_id,
        ssl_forced, caching_enabled, block_exploits, advanced_config, meta,
        allow_websocket_upgrade, http2_support, forward_scheme, enabled,
        locations, hsts_enabled, hsts_subdomains, trust_forwarded_proto
      )
      values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `,
    )
    .run(
      now,
      now,
      owner.id,
      0,
      JSON.stringify([domain]),
      forwardHost,
      forwardPort,
      0,
      cert.id,
      1,
      0,
      1,
      "",
      meta,
      0,
      1,
      "http",
      1,
      "[]",
      0,
      0,
      0,
    );
  proxyId = result.lastInsertRowid;
}

const confPath = path.join(confDir, `${proxyId}.conf`);
backup(confPath);
fs.writeFileSync(confPath, nginxConf(proxyId, cert.id), { mode: 0o644 });
db.close();

console.log(
  JSON.stringify(
    {
      domain,
      forward: `http://${forwardHost}:${forwardPort}`,
      proxyId,
      databaseBackup: `${dbPath}.bak-pre-ups-monitor-${stamp}`,
    },
    null,
    2,
  ),
);

const Database = require("better-sqlite3");

const appId = "homepage-app-ups-monitor";
const itemId = "homepage-item-ups-monitor";
const href = process.env.UPS_MONITOR_URL;
const pingUrl =
  process.env.UPS_MONITOR_HEALTH_URL ||
  (href ? `${href.replace(/\/$/, "")}/healthz` : "");
const boardName = process.env.HOMARR_BOARD_NAME || "Homelab";

if (!href) {
  throw new Error("UPS_MONITOR_URL is required");
}

async function main() {
  const db = new Database("/appdata/db/db.sqlite");
  const stamp = new Date()
    .toISOString()
    .replace(/[-:TZ.]/g, "")
    .slice(0, 14);
  const backupPath = `/appdata/db/db.sqlite.bak-pre-ups-monitor-${stamp}`;
  await db.backup(backupPath);

  const board = db.prepare("select id from board where name=?").get(boardName);
  if (!board) throw new Error(`Homarr board not found: ${boardName}`);

  const section = db
    .prepare("select id from section where board_id=? order by rowid limit 1")
    .get(board.id);
  const layout = db
    .prepare("select id from layout where board_id=? order by rowid limit 1")
    .get(board.id);
  if (!section || !layout) {
    throw new Error(`Homarr section/layout not found for board: ${boardName}`);
  }

  const existingLayout = db
    .prepare(
      `
      select x_offset, y_offset, width, height
        from item_layout
       where item_id=? and section_id=? and layout_id=?
    `,
    )
    .get(itemId, section.id, layout.id);
  const layoutRow = existingLayout || {
    x_offset: 1,
    y_offset: 3,
    width: 1,
    height: 1,
  };

  const transaction = db.transaction(() => {
    db.prepare(
      `
      insert into app (id, name, description, icon_url, href, ping_url)
      values (?, ?, ?, ?, ?, ?)
      on conflict(id) do update set
        name=excluded.name,
        description=excluded.description,
        icon_url=excluded.icon_url,
        href=excluded.href,
        ping_url=excluded.ping_url
    `,
    ).run(
      appId,
      "UPS Monitor",
      "CyberPower fleet status and power history",
      "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/ups.png",
      href,
      pingUrl,
    );

    db.prepare(
      `
      insert into item (id, board_id, kind, options, advanced_options)
      values (?, ?, 'app', ?, ?)
      on conflict(id) do update set
        board_id=excluded.board_id,
        kind=excluded.kind,
        options=excluded.options,
        advanced_options=excluded.advanced_options
    `,
    ).run(
      itemId,
      board.id,
      JSON.stringify({
        json: {
          appId,
          openInNewTab: true,
          showTitle: true,
          pingEnabled: true,
          layout: "row",
          descriptionDisplayMode: "tooltip",
        },
      }),
      JSON.stringify({ json: {} }),
    );

    db.prepare(
      `
      insert into item_layout (
        item_id, section_id, layout_id, x_offset, y_offset, width, height
      )
      values (?, ?, ?, ?, ?, ?, ?)
      on conflict(item_id, section_id, layout_id) do update set
        x_offset=excluded.x_offset,
        y_offset=excluded.y_offset,
        width=excluded.width,
        height=excluded.height
    `,
    ).run(
      itemId,
      section.id,
      layout.id,
      layoutRow.x_offset,
      layoutRow.y_offset,
      layoutRow.width,
      layoutRow.height,
    );
  });

  transaction();
  db.close();
  console.log(
    JSON.stringify(
      {
        backupPath,
        appId,
        itemId,
        href,
        pingUrl,
        layout: layoutRow,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

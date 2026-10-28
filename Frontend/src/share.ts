/** Share links: /t/<public_id> opens a trip read-only. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The public id in a share link's path (/t/<public_id>), or null for any other page. */
export function sharedIdFromPath(pathname: string): string | null {
  const match = /^\/t\/([^/]+)\/?$/.exec(pathname);
  return match && UUID.test(match[1]) ? match[1].toLowerCase() : null;
}

/** The link that opens this trip read-only, on this site. */
export function shareUrl(origin: string, publicId: string): string {
  return `${origin.replace(/\/+$/, "")}/t/${publicId}`;
}

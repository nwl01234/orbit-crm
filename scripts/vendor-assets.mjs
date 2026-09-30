import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const vendorDir = path.join(root, "static", "vendor");
const fontsDir = path.join(root, "static", "fonts");

await mkdir(vendorDir, { recursive: true });
await mkdir(fontsDir, { recursive: true });

const alpineSource = path.join(root, "node_modules", "alpinejs", "dist", "cdn.min.js");
if (existsSync(alpineSource)) {
  await cp(alpineSource, path.join(vendorDir, "alpine.min.js"));
}

async function vendorFont(packageName, familyDir) {
  const packageDir = path.join(root, "node_modules", "@fontsource-variable", packageName);
  const cssPath = path.join(packageDir, "wght.css");
  if (!existsSync(cssPath)) return "";
  const targetDir = path.join(fontsDir, familyDir);
  await mkdir(targetDir, { recursive: true });
  const css = await readFile(cssPath, "utf8");
  const re = /url\(\.\/files\/([^)]+)\)/g;
  let match;
  const files = new Set();
  while ((match = re.exec(css)) !== null) files.add(match[1]);
  await Promise.all(
    [...files].map(async (file) => {
      await cp(path.join(packageDir, "files", file), path.join(targetDir, file));
    })
  );
  return css.replace(re, `url(./fonts/${familyDir}/$1)`);
}

const interCss = await vendorFont("inter", "inter");
const interTightCss = await vendorFont("inter-tight", "inter-tight");
await writeFile(path.join(root, "static", "fonts.css"), interCss + "\n" + interTightCss, "utf8");

console.log("Vendored Alpine + variable fonts into static/");

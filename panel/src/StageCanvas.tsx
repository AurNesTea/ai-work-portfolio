import { useEffect, useRef } from "react";

type Pose = "idle" | "run" | "pause" | "win" | "fail";

type Props = {
  steps: string[];
  index: number;
  pose: Pose;
  bossVisible: boolean;
  characterUrl?: string | null;
  bossUrl?: string | null;
  backgroundUrl?: string | null;
};

function loadImage(url: string | null | undefined, img: HTMLImageElement) {
  if (url) img.src = url;
  else img.removeAttribute("src");
}

function ready(img: HTMLImageElement): boolean {
  return Boolean(img.src) && img.complete && img.naturalWidth > 0;
}

function clipText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let clipped = text;
  while (clipped.length > 1 && ctx.measureText(`${clipped}…`).width > maxWidth) {
    clipped = clipped.slice(0, -1);
  }
  return `${clipped}…`;
}

export function StageCanvas({
  steps,
  index,
  pose,
  bossVisible,
  characterUrl,
  bossUrl,
  backgroundUrl,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef({ steps, index, pose, bossVisible });
  stateRef.current = { steps, index, pose, bossVisible };

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const character = new Image();
    const boss = new Image();
    const background = new Image();
    loadImage(characterUrl, character);
    loadImage(bossUrl, boss);
    loadImage(backgroundUrl, background);

    let frame = 0;
    let raf = 0;
    let charX = 0;
    let placed = false;

    const draw = () => {
      frame += 1;
      const { steps: names, index: stepIndex, pose: stepPose, bossVisible: showBoss } =
        stateRef.current;
      const css = getComputedStyle(parent);
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(parent.clientWidth, 1);
      const height = Math.max(parent.clientHeight, 1);
      const pixelW = Math.floor(width * dpr);
      const pixelH = Math.floor(height * dpr);
      if (canvas.width !== pixelW || canvas.height !== pixelH) {
        canvas.width = pixelW;
        canvas.height = pixelH;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const dark = document.documentElement.dataset.scheme === "dark";
      const grassY = height * 0.68;
      if (ready(background)) {
        ctx.drawImage(background, 0, 0, width, height);
      } else if (dark) {
        const sky = ctx.createLinearGradient(0, 0, 0, grassY);
        sky.addColorStop(0, "#243038");
        sky.addColorStop(1, "#1c1b19");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, grassY);
        ctx.fillStyle = "#3d5346";
        ctx.fillRect(0, grassY - 8, width, 14);
        ctx.fillStyle = "#3a342e";
        ctx.fillRect(0, grassY + 6, width, height - grassY);
      } else {
        const sky = ctx.createLinearGradient(0, 0, 0, grassY);
        sky.addColorStop(0, "#8ec5ea");
        sky.addColorStop(1, "#e7f4ff");
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, grassY);
        ctx.fillStyle = "#3f8f46";
        ctx.fillRect(0, grassY - 10, width, 16);
        ctx.fillStyle = "#b7b1a8";
        ctx.fillRect(0, grassY + 6, width, height - grassY);
        ctx.strokeStyle = "rgba(90, 84, 76, 0.28)";
        ctx.lineWidth = 1;
        for (let y = grassY + 28; y < height; y += 22) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(width, y);
          ctx.stroke();
        }
      }

      const count = Math.max(names.length, 1);
      const span = Math.max(count - 1, 1);
      const target = width * (0.18 + (stepIndex / span) * 0.22);
      if (!placed) {
        charX = target;
        placed = true;
      }
      charX += (target - charX) * (stepPose === "run" ? 0.08 : 0.18);
      const bob = stepPose === "run" ? Math.sin(frame / 8) * 4 : 0;
      const ink = css.getPropertyValue("--ink").trim() || "#1f1d1a";
      const body = Math.max(64, height * 0.16);

      names.forEach((name, i) => {
        const x = width * (0.18 + (i / span) * 0.22);
        const passed = i < stepIndex || (stepPose === "win" && i <= stepIndex);
        const active = i === stepIndex;
        ctx.fillStyle = active ? "#f4efe6" : passed ? "#d5e0d8" : "rgba(255,255,255,0.55)";
        ctx.beginPath();
        ctx.roundRect(x - 36, grassY - 18, 72, 10, 3);
        ctx.fill();
        ctx.fillStyle = dark ? "#ece7df" : "#1f1d1a";
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        const labelY = active ? grassY - body - 14 : grassY - 22;
        ctx.fillText(clipText(ctx, name, 68), x, labelY);
      });

      const feet = grassY - bob;
      if (ready(character)) {
        ctx.drawImage(character, charX - body / 2, feet - body, body, body);
      } else {
        ctx.fillStyle = ink;
        ctx.beginPath();
        ctx.moveTo(charX, feet - body);
        ctx.lineTo(charX - body * 0.28, feet);
        ctx.lineTo(charX + body * 0.28, feet);
        ctx.closePath();
        ctx.fill();
      }

      if (showBoss) {
        const bossSize = Math.max(120, height * 0.34);
        const bossX = width * 0.58;
        const bossY = grassY - bossSize + Math.sin(frame / 20) * 3;
        if (ready(boss)) {
          ctx.drawImage(boss, bossX, bossY, bossSize, bossSize);
        } else {
          ctx.fillStyle = css.getPropertyValue("--fail").trim() || "#8a453e";
          ctx.beginPath();
          ctx.arc(bossX + bossSize / 2, bossY + bossSize * 0.55, bossSize * 0.28, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [characterUrl, bossUrl, backgroundUrl]);

  return (
    <div className="stage-view">
      <canvas ref={canvasRef} aria-hidden="true" />
    </div>
  );
}

/**
 * kinearc-gl3d.js — Zero-Dependency Deterministic WebGL2 PBR + High-Craft 2D Runtime
 * Supports ?t=<sec>, ?scale=<S> (1080p -> 4K 3840x2160), window.kinearc,
 * 3-point tungsten/titanium PBR lighting with planar floor reflection,
 * machined anodized panels, tactile cursor choreography, kinetic typography,
 * and deterministic 35mm film grain.
 */

export function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

export function clamp01(v) {
  return Math.min(1, Math.max(0, v));
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

export function smoothstep(edge0, edge1, x) {
  const t = clamp01((x - edge0) / Math.max(1e-6, edge1 - edge0));
  return t * t * (3 - 2 * t);
}

export function easeOutCubic(t) {
  const u = 1 - clamp01(t);
  return 1 - u * u * u;
}

export function easeInOutCubic(t) {
  const p = clamp01(t);
  return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
}

export function easeOutExpo(t) {
  const p = clamp01(t);
  return p >= 1 ? 1 : 1 - Math.pow(2, -10 * p);
}

export function springProgress(tSec, { delay = 0, duration = 0.65, damping = 14, stiffness = 170 } = {}) {
  const local = tSec - delay;
  if (local <= 0) return 0;
  if (local >= duration * 2.2) return 1;
  const omega = Math.sqrt(stiffness);
  const zeta = damping / (2 * omega);
  if (zeta < 1) {
    const wd = omega * Math.sqrt(1 - zeta * zeta);
    const val = 1 - Math.exp(-zeta * omega * local) * (Math.cos(wd * local) + (zeta / Math.sqrt(1 - zeta * zeta)) * Math.sin(wd * local));
    return clamp(val, 0, 1.25);
  }
  return clamp01(1 - Math.exp(-omega * local) * (1 + omega * local));
}

// ---------- Minimal 4x4 Matrix Math ----------
export const mat4 = {
  identity() {
    return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  },
  multiply(a, b) {
    const out = new Float32Array(16);
    for (let col = 0; col < 4; col++) {
      const b0 = b[col * 4], b1 = b[col * 4 + 1], b2 = b[col * 4 + 2], b3 = b[col * 4 + 3];
      out[col * 4]     = a[0] * b0 + a[4] * b1 + a[8]  * b2 + a[12] * b3;
      out[col * 4 + 1] = a[1] * b0 + a[5] * b1 + a[9]  * b2 + a[13] * b3;
      out[col * 4 + 2] = a[2] * b0 + a[6] * b1 + a[10] * b2 + a[14] * b3;
      out[col * 4 + 3] = a[3] * b0 + a[7] * b1 + a[11] * b2 + a[15] * b3;
    }
    return out;
  },
  perspective(fovRad, aspect, near, far) {
    const f = 1 / Math.tan(fovRad / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ]);
  },
  lookAt(eye, target, up = [0, 1, 0]) {
    let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
    const zLen = Math.hypot(zx, zy, zz) || 1;
    zx /= zLen; zy /= zLen; zz /= zLen;

    let xx = up[1] * zz - up[2] * zy;
    let xy = up[2] * zx - up[0] * zz;
    let xz = up[0] * zy - up[1] * zx;
    const xLen = Math.hypot(xx, xy, xz) || 1;
    xx /= xLen; xy /= xLen; xz /= xLen;

    const yx = zy * xz - zz * xy;
    const yy = zz * xx - zx * xz;
    const yz = zx * xy - zy * xx;

    return new Float32Array([
      xx, yx, zx, 0,
      xy, yy, zy, 0,
      xz, yz, zz, 0,
      -(xx * eye[0] + xy * eye[1] + xz * eye[2]),
      -(yx * eye[0] + yy * eye[1] + yz * eye[2]),
      -(zx * eye[0] + zy * eye[1] + zz * eye[2]),
      1,
    ]);
  },
  transform({ pos = [0, 0, 0], rot = [0, 0, 0], scale = [1, 1, 1] } = {}) {
    const [sx, sy, sz] = typeof scale === "number" ? [scale, scale, scale] : scale;
    const [rx, ry, rz] = rot;
    const cx = Math.cos(rx), sxr = Math.sin(rx);
    const cy = Math.cos(ry), syr = Math.sin(ry);
    const cz = Math.cos(rz), szr = Math.sin(rz);

    const rotX = new Float32Array([1, 0, 0, 0, 0, cx, sxr, 0, 0, -sxr, cx, 0, 0, 0, 0, 1]);
    const rotY = new Float32Array([cy, 0, -syr, 0, 0, 1, 0, 0, syr, 0, cy, 0, 0, 0, 0, 1]);
    const rotZ = new Float32Array([cz, szr, 0, 0, -szr, cz, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
    const rMat = mat4.multiply(rotZ, mat4.multiply(rotY, rotX));
    rMat[0] *= sx; rMat[1] *= sx; rMat[2] *= sx;
    rMat[4] *= sy; rMat[5] *= sy; rMat[6] *= sy;
    rMat[8] *= sz; rMat[9] *= sz; rMat[10] *= sz;
    rMat[12] = pos[0]; rMat[13] = pos[1]; rMat[14] = pos[2];
    return rMat;
  },
};

function computeFlatNormalsMesh(triPositions) {
  const positions = new Float32Array(triPositions);
  const normals = new Float32Array(triPositions.length);
  for (let i = 0; i < triPositions.length; i += 9) {
    const ax = triPositions[i], ay = triPositions[i + 1], az = triPositions[i + 2];
    const bx = triPositions[i + 3], by = triPositions[i + 4], bz = triPositions[i + 5];
    const cx = triPositions[i + 6], cy = triPositions[i + 7], cz = triPositions[i + 8];
    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1;
    nx /= len; ny /= len; nz /= len;
    normals[i] = normals[i + 3] = normals[i + 6] = nx;
    normals[i + 1] = normals[i + 4] = normals[i + 7] = ny;
    normals[i + 2] = normals[i + 5] = normals[i + 8] = nz;
  }
  return { positions, normals, vertexCount: triPositions.length / 3 };
}

export function createCrystalMesh(sides = 8, radius = 1.0, height = 2.15, bevel = 0.24) {
  const pts = [];
  const halfH = height * 0.5;
  const shoulderY = halfH * (1 - bevel);
  const pushTri = (a, b, c) => { pts.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]); };
  for (let i = 0; i < sides; i++) {
    const a0 = (i / sides) * Math.PI * 2;
    const a1 = ((i + 1) / sides) * Math.PI * 2;
    const c0 = [Math.cos(a0) * radius, 0, Math.sin(a0) * radius];
    const c1 = [Math.cos(a1) * radius, 0, Math.sin(a1) * radius];
    const top0 = [Math.cos(a0) * radius * 0.62, shoulderY, Math.sin(a0) * radius * 0.62];
    const top1 = [Math.cos(a1) * radius * 0.62, shoulderY, Math.sin(a1) * radius * 0.62];
    const bot0 = [Math.cos(a0) * radius * 0.62, -shoulderY, Math.sin(a0) * radius * 0.62];
    const bot1 = [Math.cos(a1) * radius * 0.62, -shoulderY, Math.sin(a1) * radius * 0.62];
    const apex = [0, halfH, 0];
    const nadir = [0, -halfH, 0];
    pushTri(c0, c1, top1);
    pushTri(c0, top1, top0);
    pushTri(top0, top1, apex);
    pushTri(c1, c0, bot0);
    pushTri(c1, bot0, bot1);
    pushTri(bot1, bot0, nadir);
  }
  return computeFlatNormalsMesh(pts);
}

export function createBoxMesh(w = 1, h = 1, d = 1) {
  const hw = w * 0.5, hh = h * 0.5, hd = d * 0.5;
  const faces = [
    [[hw, -hh, hd], [hw, hh, hd], [-hw, hh, hd], [-hw, -hh, hd]],
    [[-hw, -hh, -hd], [-hw, hh, -hd], [hw, hh, -hd], [hw, -hh, -hd]],
    [[-hw, hh, hd], [hw, hh, hd], [hw, hh, -hd], [-hw, hh, -hd]],
    [[-hw, -hh, -hd], [hw, -hh, -hd], [hw, -hh, hd], [-hw, -hh, hd]],
    [[hw, -hh, -hd], [hw, hh, -hd], [hw, hh, hd], [hw, -hh, hd]],
    [[-hw, -hh, hd], [-hw, hh, hd], [-hw, hh, -hd], [-hw, -hh, -hd]],
  ];
  const pts = [];
  for (const [a, b, c, e] of faces) {
    pts.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
    pts.push(a[0], a[1], a[2], c[0], c[1], c[2], e[0], e[1], e[2]);
  }
  return computeFlatNormalsMesh(pts);
}

export function createChamferSlabMesh(w = 2.0, h = 1.2, d = 0.22, bevel = 0.06) {
  const hw = w * 0.5, hh = h * 0.5, hd = d * 0.5;
  const bev = Math.max(0.005, Math.min(bevel, hw * 0.45, hh * 0.45, hd * 0.45));
  const bw = hw - bev, bh = hh - bev, bd = hd - bev;
  const pts = [];
  const pushTri = (a, b, c) => {
    pts.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
  };
  const pushQuad = (a, b, c, e) => {
    pushTri(a, b, c);
    pushTri(a, c, e);
  };

  // 6 flat faces (inset along orthogonal axes)
  pushQuad([-bw, -bh,  hd], [ bw, -bh,  hd], [ bw,  bh,  hd], [-bw,  bh,  hd]); // +Z front
  pushQuad([ bw, -bh, -hd], [-bw, -bh, -hd], [-bw,  bh, -hd], [ bw,  bh, -hd]); // -Z back
  pushQuad([ hw, -bh,  bd], [ hw, -bh, -bd], [ hw,  bh, -bd], [ hw,  bh,  bd]); // +X right
  pushQuad([-hw, -bh, -bd], [-hw, -bh,  bd], [-hw,  bh,  bd], [-hw,  bh, -bd]); // -X left
  pushQuad([-bw,  hh,  bd], [ bw,  hh,  bd], [ bw,  hh, -bd], [-bw,  hh, -bd]); // +Y top
  pushQuad([-bw, -hh, -bd], [ bw, -hh, -bd], [ bw, -hh,  bd], [-bw, -hh,  bd]); // -Y bottom

  // 4 front bevel strips
  pushQuad([-bw,  bh,  hd], [ bw,  bh,  hd], [ bw,  hh,  bd], [-bw,  hh,  bd]); // front-top
  pushQuad([-bw, -hh,  bd], [ bw, -hh,  bd], [ bw, -bh,  hd], [-bw, -bh,  hd]); // front-bot
  pushQuad([ bw, -bh,  hd], [ hw, -bh,  bd], [ hw,  bh,  bd], [ bw,  bh,  hd]); // front-right
  pushQuad([-hw, -bh,  bd], [-bw, -bh,  hd], [-bw,  bh,  hd], [-hw,  bh,  bd]); // front-left

  // 4 back bevel strips
  pushQuad([ bw,  bh, -hd], [-bw,  bh, -hd], [-bw,  hh, -bd], [ bw,  hh, -bd]); // back-top
  pushQuad([ bw, -hh, -bd], [-bw, -hh, -bd], [-bw, -bh, -hd], [ bw, -bh, -hd]); // back-bot
  pushQuad([ hw, -bh, -bd], [ bw, -bh, -hd], [ bw,  bh, -hd], [ hw,  bh, -bd]); // back-right
  pushQuad([-bw, -bh, -hd], [-hw, -bh, -bd], [-hw,  bh, -bd], [-bw,  bh, -hd]); // back-left

  // 4 axial side bevel strips
  pushQuad([ bw,  hh,  bd], [ hw,  bh,  bd], [ hw,  bh, -bd], [ bw,  hh, -bd]); // top-right
  pushQuad([-hw,  bh,  bd], [-bw,  hh,  bd], [-bw,  hh, -bd], [-hw,  bh, -bd]); // top-left
  pushQuad([ hw, -bh,  bd], [ bw, -hh,  bd], [ bw, -hh, -bd], [ hw, -bh, -bd]); // bot-right
  pushQuad([-bw, -hh,  bd], [-hw, -bh,  bd], [-hw, -bh, -bd], [-bw, -hh, -bd]); // bot-left

  // 8 corner chamfer triangles (completing watertight 2-manifold)
  pushTri([ bw,  bh,  hd], [ hw,  bh,  bd], [ bw,  hh,  bd]); // +X+Y+Z
  pushTri([-bw,  bh,  hd], [-bw,  hh,  bd], [-hw,  bh,  bd]); // -X+Y+Z
  pushTri([ bw, -bh,  hd], [ bw, -hh,  bd], [ hw, -bh,  bd]); // +X-Y+Z
  pushTri([-bw, -bh,  hd], [-hw, -bh,  bd], [-bw, -hh,  bd]); // -X-Y+Z
  pushTri([ bw,  bh, -hd], [ bw,  hh, -bd], [ hw,  bh, -bd]); // +X+Y-Z
  pushTri([-bw,  bh, -hd], [-hw,  bh, -bd], [-bw,  hh, -bd]); // -X+Y-Z
  pushTri([ bw, -bh, -hd], [ hw, -bh, -bd], [ bw, -hh, -bd]); // +X-Y-Z
  pushTri([-bw, -bh, -hd], [-bw, -hh, -bd], [-hw, -bh, -bd]); // -X-Y-Z

  return computeFlatNormalsMesh(pts);
}

export function createCylinderMesh(rTop = 0.8, rBot = 0.8, height = 0.4, segs = 48) {
  const pts = [];
  const hh = height * 0.5;
  const pushTri = (a, b, c) => pts.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
  for (let i = 0; i < segs; i++) {
    const a0 = (i / segs) * Math.PI * 2;
    const a1 = ((i + 1) / segs) * Math.PI * 2;
    const c0 = Math.cos(a0), s0 = Math.sin(a0);
    const c1 = Math.cos(a1), s1 = Math.sin(a1);
    const t0 = [c0 * rTop, hh, s0 * rTop];
    const t1 = [c1 * rTop, hh, s1 * rTop];
    const b0 = [c0 * rBot, -hh, s0 * rBot];
    const b1 = [c1 * rBot, -hh, s1 * rBot];
    pushTri(b0, b1, t1);
    pushTri(b0, t1, t0);
    pushTri([0, hh, 0], t1, t0);
    pushTri([0, -hh, 0], b0, b1);
  }
  return computeFlatNormalsMesh(pts);
}

export function createTorusMesh(majorR = 1.6, minorR = 0.09, segU = 64, segV = 16) {
  const pts = [];
  const norms = [];
  const p = (u, v) => {
    const cu = Math.cos(u), su = Math.sin(u), cv = Math.cos(v), sv = Math.sin(v);
    const x = (majorR + minorR * cv) * cu;
    const y = (majorR + minorR * cv) * su;
    const z = minorR * sv;
    return { pos: [x, y, z], nrm: [cv * cu, cv * su, sv] };
  };
  for (let i = 0; i < segU; i++) {
    const u0 = (i / segU) * Math.PI * 2;
    const u1 = ((i + 1) / segU) * Math.PI * 2;
    for (let j = 0; j < segV; j++) {
      const v0 = (j / segV) * Math.PI * 2;
      const v1 = ((j + 1) / segV) * Math.PI * 2;
      const p00 = p(u0, v0), p10 = p(u1, v0), p11 = p(u1, v1), p01 = p(u0, v1);
      for (const vtx of [p00, p10, p11, p00, p11, p01]) {
        pts.push(...vtx.pos);
        norms.push(...vtx.nrm);
      }
    }
  }
  return { positions: new Float32Array(pts), normals: new Float32Array(norms), vertexCount: pts.length / 3 };
}

export function createTorusKnotMesh(R = 1.15, tube = 0.22, pVal = 2, qVal = 3, segU = 140, segV = 14) {
  const pts = [];
  const norms = [];
  const curve = (u) => {
    const r = 0.5 * (2 + Math.sin(qVal * u));
    return [
      R * r * Math.cos(pVal * u),
      R * r * Math.sin(pVal * u),
      R * 0.55 * Math.cos(qVal * u),
    ];
  };
  const tangent = (u) => {
    const e = 0.002;
    const a = curve(u - e), b = curve(u + e);
    const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
    const len = Math.hypot(dx, dy, dz) || 1;
    return [dx / len, dy / len, dz / len];
  };
  const ring = (u) => {
    const center = curve(u);
    const T = tangent(u);
    // Use smooth radial reference aligned with the knot's major angle so the tube frame never flips discontinuously.
    const ref = pVal !== 0
      ? [Math.cos(pVal * u), Math.sin(pVal * u), 0]
      : (Math.hypot(T[0], T[1]) > 0.1 ? [0, 0, 1] : [1, 0, 0]);
    let bx = T[1] * ref[2] - T[2] * ref[1];
    let by = T[2] * ref[0] - T[0] * ref[2];
    let bz = T[0] * ref[1] - T[1] * ref[0];
    const bl = Math.hypot(bx, by, bz) || 1;
    bx /= bl; by /= bl; bz /= bl;
    const nx = by * T[2] - bz * T[1];
    const ny = bz * T[0] - bx * T[2];
    const nz = bx * T[1] - by * T[0];
    const out = [];
    for (let j = 0; j <= segV; j++) {
      const a = (j / segV) * Math.PI * 2;
      const ca = Math.cos(a), sa = Math.sin(a);
      const rn = [ca * bx + sa * nx, ca * by + sa * ny, ca * bz + sa * nz];
      out.push({
        pos: [center[0] + tube * rn[0], center[1] + tube * rn[1], center[2] + tube * rn[2]],
        nrm: rn,
      });
    }
    return out;
  };
  for (let i = 0; i < segU; i++) {
    const r0 = ring((i / segU) * Math.PI * 2);
    const r1 = ring(((i + 1) / segU) * Math.PI * 2);
    for (let j = 0; j < segV; j++) {
      const p00 = r0[j], p10 = r1[j], p11 = r1[j + 1], p01 = r0[j + 1];
      for (const vtx of [p00, p10, p11, p00, p11, p01]) {
        pts.push(...vtx.pos);
        norms.push(...vtx.nrm);
      }
    }
  }
  return { positions: new Float32Array(pts), normals: new Float32Array(norms), vertexCount: pts.length / 3 };
}

// ---------- WebGL2 3-Point Tungsten/Titanium PBR Renderer with Planar Reflection ----------
export function createWebGLRenderer(width, height, scale = 1) {
  const glCanvas = document.createElement("canvas");
  glCanvas.width = Math.max(2, Math.round(width * scale));
  glCanvas.height = Math.max(2, Math.round(height * scale));
  const gl = glCanvas.getContext("webgl2", {
    alpha: true,
    antialias: true,
    depth: true,
    preserveDrawingBuffer: true,
  });
  if (!gl) {
    return null;
  }

  const vsSrc = `#version 300 es
    in vec3 aPos;
    in vec3 aNrm;
    uniform mat4 uMVP;
    uniform mat4 uModel;
    out vec3 vNrm;
    out vec3 vWorldPos;
    void main() {
      vec4 wp = uModel * vec4(aPos, 1.0);
      vWorldPos = wp.xyz;
      vNrm = transpose(inverse(mat3(uModel))) * aNrm;
      gl_Position = uMVP * vec4(aPos, 1.0);
    }
  `;

  const fsSrc = `#version 300 es
    precision highp float;
    in vec3 vNrm;
    in vec3 vWorldPos;
    uniform vec3 uCameraPos;
    uniform vec3 uBaseColor;
    uniform vec3 uEmissive;
    uniform vec3 uKeyColor;
    uniform vec3 uFillColor;
    uniform float uRoughness;
    uniform float uMetallic;
    uniform float uAlpha;
    out vec4 outColor;

    void main() {
      vec3 N = normalize(vNrm);
      vec3 V = normalize(uCameraPos - vWorldPos);

      // 3-point lighting: Warm Key, Cool Fill, Razor Back Rim
      vec3 L1 = normalize(vec3(3.8, 4.8, 4.0));
      vec3 L2 = normalize(vec3(-4.2, -1.8, 2.8));
      vec3 L3 = normalize(vec3(0.0, 3.2, -4.5));
      vec3 H1 = normalize(L1 + V);
      vec3 H2 = normalize(L2 + V);
      vec3 H3 = normalize(L3 + V);

      float ndotl1 = max(dot(N, L1), 0.0);
      float ndotl2 = max(dot(N, L2), 0.0);
      float ndotl3 = max(dot(N, L3), 0.0);
      float shininess = mix(160.0, 12.0, clamp(uRoughness, 0.04, 0.98));
      float spec1 = pow(max(dot(N, H1), 0.0), shininess);
      float spec2 = pow(max(dot(N, H2), 0.0), shininess * 0.65);
      float spec3 = pow(max(dot(N, H3), 0.0), shininess * 0.85);

      float fresnel = pow(1.0 - max(dot(N, V), 0.0), 3.4);
      vec3 envTop = vec3(0.24, 0.23, 0.22);
      vec3 envBot = vec3(0.04, 0.04, 0.05);
      vec3 envTint = mix(envBot, envTop, N.y * 0.5 + 0.5);

      vec3 diff = uBaseColor * (0.12 + ndotl1 * 0.68 * uKeyColor + ndotl2 * 0.32 * uFillColor + ndotl3 * 0.22);
      vec3 specCol = mix(vec3(0.96), uBaseColor + vec3(0.22), uMetallic);
      vec3 spec = specCol * (spec1 * 1.10 * uKeyColor + spec2 * 0.42 * uFillColor + spec3 * 0.55 * vec3(1.0, 0.92, 0.80));
      vec3 rim = mix(uKeyColor, vec3(1.0, 0.95, 0.88), 0.5) * fresnel * (0.48 + 0.48 * uMetallic);

      vec3 col = diff * (1.0 - 0.58 * uMetallic) + envTint * (0.16 + 0.38 * uMetallic) + spec + rim + uEmissive;
      outColor = vec4(col, uAlpha);
    }
  `;

  function compile(type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(sh) || "Shader compile failed");
    }
    return sh;
  }

  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSrc));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fsSrc));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(prog) || "Program link failed");
  }

  const aPosLoc = gl.getAttribLocation(prog, "aPos");
  const aNrmLoc = gl.getAttribLocation(prog, "aNrm");
  const uMVP = gl.getUniformLocation(prog, "uMVP");
  const uModel = gl.getUniformLocation(prog, "uModel");
  const uCameraPos = gl.getUniformLocation(prog, "uCameraPos");
  const uBaseColor = gl.getUniformLocation(prog, "uBaseColor");
  const uEmissive = gl.getUniformLocation(prog, "uEmissive");
  const uKeyColor = gl.getUniformLocation(prog, "uKeyColor");
  const uFillColor = gl.getUniformLocation(prog, "uFillColor");
  const uRoughness = gl.getUniformLocation(prog, "uRoughness");
  const uMetallic = gl.getUniformLocation(prog, "uMetallic");
  const uAlpha = gl.getUniformLocation(prog, "uAlpha");

  const meshCache = new WeakMap();
  function uploadMesh(mesh) {
    if (meshCache.has(mesh)) return meshCache.get(mesh);
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);

    const posBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aPosLoc);
    gl.vertexAttribPointer(aPosLoc, 3, gl.FLOAT, false, 0, 0);

    const nrmBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, nrmBuf);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.normals, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(aNrmLoc);
    gl.vertexAttribPointer(aNrmLoc, 3, gl.FLOAT, false, 0, 0);

    gl.bindVertexArray(null);
    const rec = { vao, count: mesh.vertexCount };
    meshCache.set(mesh, rec);
    return rec;
  }

  return {
    canvas: glCanvas,
    render({
      cameraPos = [0, 0.9, 6.2],
      cameraTarget = [0, 0, 0],
      fovDeg = 40,
      keyColor = [1.0, 0.86, 0.68],
      fillColor = [0.58, 0.72, 0.92],
      floorY = null,
      reflectionAlpha = 0.16,
      objects = [],
    }) {
      gl.viewport(0, 0, glCanvas.width, glCanvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      gl.useProgram(prog);
      const proj = mat4.perspective((fovDeg * Math.PI) / 180, glCanvas.width / glCanvas.height, 0.1, 80);
      const view = mat4.lookAt(cameraPos, cameraTarget);
      const vp = mat4.multiply(proj, view);

      gl.uniform3fv(uCameraPos, cameraPos);
      gl.uniform3fv(uKeyColor, keyColor);
      gl.uniform3fv(uFillColor, fillColor);

      // Optional planar floor reflection pass
      if (floorY !== null && Number.isFinite(floorY)) {
        gl.depthMask(false);
        for (const obj of objects) {
          if (obj.skipReflection) continue;
          const rec = uploadMesh(obj.mesh);
          const pos = obj.pos || [0, 0, 0];
          const rot = obj.rot || [0, 0, 0];
          const sc = typeof obj.scale === "number" ? [obj.scale, obj.scale, obj.scale] : (obj.scale || [1, 1, 1]);
          const reflObj = {
            pos: [pos[0], 2 * floorY - pos[1], pos[2]],
            rot: [-rot[0], rot[1], -rot[2]],
            scale: [sc[0], -sc[1], sc[2]],
          };
          const model = mat4.transform(reflObj);
          const mvp = mat4.multiply(vp, model);
          gl.uniformMatrix4fv(uMVP, false, mvp);
          gl.uniformMatrix4fv(uModel, false, model);
          gl.uniform3fv(uBaseColor, obj.color || [0.75, 0.75, 0.78]);
          gl.uniform3fv(uEmissive, [0, 0, 0]);
          gl.uniform1f(uRoughness, Math.min(0.95, (obj.roughness ?? 0.25) + 0.35));
          gl.uniform1f(uMetallic, obj.metallic ?? 0.78);
          gl.uniform1f(uAlpha, (obj.alpha ?? 1.0) * reflectionAlpha);
          gl.bindVertexArray(rec.vao);
          gl.drawArrays(gl.TRIANGLES, 0, rec.count);
        }
        gl.depthMask(true);
      }

      for (const obj of objects) {
        const rec = uploadMesh(obj.mesh);
        const model = mat4.transform(obj);
        const mvp = mat4.multiply(vp, model);
        gl.uniformMatrix4fv(uMVP, false, mvp);
        gl.uniformMatrix4fv(uModel, false, model);
        gl.uniform3fv(uBaseColor, obj.color || [0.82, 0.83, 0.86]);
        gl.uniform3fv(uEmissive, obj.emissive || [0, 0, 0]);
        gl.uniform1f(uRoughness, obj.roughness ?? 0.22);
        gl.uniform1f(uMetallic, obj.metallic ?? 0.78);
        gl.uniform1f(uAlpha, obj.alpha ?? 1.0);
        gl.bindVertexArray(rec.vao);
        gl.drawArrays(gl.TRIANGLES, 0, rec.count);
      }
      gl.bindVertexArray(null);
      gl.flush();
    },
  };
}

// ---------- High-Craft Anti-Slop 2D & Post-Processing Helpers ----------
export function roundRectPath(ctx, x, y, w, h, r = 14) {
  const rad = Math.min(r, w * 0.5, h * 0.5);
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.lineTo(x + w - rad, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rad);
  ctx.lineTo(x + w, y + h - rad);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
  ctx.lineTo(x + rad, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rad);
  ctx.lineTo(x, y + rad);
  ctx.quadraticCurveTo(x, y, x + rad, y);
  ctx.closePath();
}

export function drawCraftBackdrop(ctx, W, H, t, {
  theme = "obsidian",
  warmPool = "rgba(245, 158, 11, 0.11)",
  coolPool = "rgba(56, 189, 248, 0.07)",
  floorHorizon = null,
  showCrosshairs = true,
} = {}) {
  const palettes = {
    obsidian: ["#121215", "#0a0a0c", "#050507"],
    editorial: ["#161514", "#0e0d0c", "#080707"],
    optical: ["#0e1014", "#08090c", "#040507"],
    pearl: ["#ffffff", "#f6f7fb", "#ececf8"],
    midnight: ["#131026", "#090714", "#05040c"],
  };
  const [c0, c1, c2] = palettes[theme] || palettes.obsidian;
  const bg = ctx.createRadialGradient(W * 0.5, H * 0.38, 40, W * 0.5, H * 0.5, Math.max(W, H) * 0.82);
  bg.addColorStop(0, c0);
  bg.addColorStop(0.55, c1);
  bg.addColorStop(1, c2);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Volumetric key & fill light pools (subtle, non-neon)
  ctx.save();
  const driftX = Math.sin(t * 0.55) * 36;
  const warmRadius = Math.max(W, H) * 0.42;
  const gWarm = ctx.createRadialGradient(W * 0.34 + driftX, H * 0.28, 10, W * 0.34 + driftX, H * 0.28, warmRadius);
  gWarm.addColorStop(0, warmPool);
  gWarm.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = gWarm;
  ctx.fillRect(0, 0, W, H);

  const gCool = ctx.createRadialGradient(W * 0.74 - driftX, H * 0.68, 10, W * 0.74 - driftX, H * 0.68, warmRadius * 0.92);
  gCool.addColorStop(0, coolPool);
  gCool.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = gCool;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();

  // Optional anodized ground reflection horizon line
  if (floorHorizon !== null) {
    ctx.save();
    const fy = H * floorHorizon;
    const fGrad = ctx.createLinearGradient(0, fy, 0, H);
    fGrad.addColorStop(0, "rgba(255, 255, 255, 0.035)");
    fGrad.addColorStop(0.15, "rgba(10, 10, 12, 0.45)");
    fGrad.addColorStop(1, "rgba(4, 4, 6, 0.85)");
    ctx.fillStyle = fGrad;
    ctx.fillRect(0, fy, W, H - fy);

    const hLine = ctx.createLinearGradient(W * 0.1, fy, W * 0.9, fy);
    hLine.addColorStop(0, "rgba(255,255,255,0)");
    hLine.addColorStop(0.5, "rgba(244, 244, 245, 0.14)");
    hLine.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = hLine;
    ctx.fillRect(W * 0.1, fy - 0.5, W * 0.8, 1);
    ctx.restore();
  }

  // Architectural precision micro-crosshairs (240px calibration grid)
  if (showCrosshairs) {
    ctx.save();
    ctx.strokeStyle = "rgba(244, 244, 245, 0.065)";
    ctx.lineWidth = 1;
    for (let x = 240; x < W; x += 240) {
      for (let y = 180; y < H; y += 240) {
        ctx.beginPath();
        ctx.moveTo(x - 4, y);
        ctx.lineTo(x + 4, y);
        ctx.moveTo(x, y - 4);
        ctx.lineTo(x, y + 4);
        ctx.stroke();
      }
    }
    ctx.restore();
  }
}

export function drawMachinedPanel(ctx, x, y, w, h, {
  radius = 14,
  surfaceTop = "rgba(24, 24, 28, 0.94)",
  surfaceBot = "rgba(14, 14, 17, 0.96)",
  border = "rgba(255, 255, 255, 0.09)",
  bevelTop = "rgba(255, 255, 255, 0.22)",
  accentColor = null,
  headerH = 0,
  title = null,
  tag = null,
  elevation = 32,
} = {}) {
  ctx.save();
  // Deep physical contact + ambient shadow
  ctx.shadowColor = "rgba(0, 0, 0, 0.72)";
  ctx.shadowBlur = elevation;
  ctx.shadowOffsetY = Math.round(elevation * 0.42);
  roundRectPath(ctx, x, y, w, h, radius);
  const surf = ctx.createLinearGradient(x, y, x, y + h);
  surf.addColorStop(0, surfaceTop);
  surf.addColorStop(1, surfaceBot);
  ctx.fillStyle = surf;
  ctx.fill();

  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;

  if (headerH > 0) {
    ctx.save();
    roundRectPath(ctx, x, y, w, h, radius);
    ctx.clip();
    ctx.fillStyle = "rgba(255, 255, 255, 0.028)";
    ctx.fillRect(x, y, w, headerH);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.07)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, y + headerH);
    ctx.lineTo(x + w, y + headerH);
    ctx.stroke();

    // Machined hardware status dots
    for (let i = 0; i < 3; i++) {
      ctx.fillStyle = i === 0 && accentColor ? accentColor : "rgba(255, 255, 255, 0.18)";
      ctx.beginPath();
      ctx.arc(x + 22 + i * 14, y + headerH * 0.5, 4, 0, Math.PI * 2);
      ctx.fill();
    }
    if (title) {
      ctx.font = '600 13px ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace';
      ctx.fillStyle = "rgba(228, 228, 231, 0.78)";
      ctx.textBaseline = "middle";
      ctx.fillText(title, x + 70, y + headerH * 0.5 + 0.5);
    }
    if (tag) {
      ctx.font = '700 11px ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace';
      const tw = ctx.measureText(tag).width;
      ctx.fillStyle = accentColor || "#f59e0b";
      ctx.textBaseline = "middle";
      ctx.fillText(tag, x + w - tw - 20, y + headerH * 0.5 + 0.5);
    }
    ctx.restore();
  }

  // Outer anodized rim
  roundRectPath(ctx, x, y, w, h, radius);
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = border;
  ctx.stroke();

  // Top 1px machined specular edge catch
  const topGlint = ctx.createLinearGradient(x + radius, y, x + w - radius, y);
  topGlint.addColorStop(0, "rgba(255,255,255,0.03)");
  topGlint.addColorStop(0.35, bevelTop);
  topGlint.addColorStop(0.65, bevelTop);
  topGlint.addColorStop(1, "rgba(255,255,255,0.03)");
  ctx.strokeStyle = topGlint;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(x + radius, y + 0.8);
  ctx.lineTo(x + w - radius, y + 0.8);
  ctx.stroke();

  if (accentColor) {
    const acc = ctx.createLinearGradient(x + radius, y, x + radius + 140, y);
    acc.addColorStop(0, accentColor);
    acc.addColorStop(1, "rgba(0,0,0,0)");
    ctx.strokeStyle = acc;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x + radius, y + 0.8);
    ctx.lineTo(Math.min(x + w - radius, x + radius + 140), y + 0.8);
    ctx.stroke();
  }
  ctx.restore();
}

export function drawTactileCursor(ctx, x, y, {
  pressed = false,
  clickProgress = 0,
  color = "#fafafa",
  accent = "#f59e0b",
  label = null,
} = {}) {
  ctx.save();
  if (clickProgress > 0 && clickProgress < 1) {
    const r = 8 + easeOutCubic(clickProgress) * 34;
    ctx.strokeStyle = accent;
    ctx.globalAlpha = (1 - clickProgress) * 0.85;
    ctx.lineWidth = 2.2 * (1 - clickProgress * 0.5);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  ctx.translate(x, y);
  const sc = pressed ? 0.88 : 1.0;
  ctx.scale(sc, sc);

  ctx.shadowColor = "rgba(0, 0, 0, 0.65)";
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 4;

  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(0, 22);
  ctx.lineTo(5.8, 17.2);
  ctx.lineTo(10.2, 26.5);
  ctx.lineTo(14.0, 24.6);
  ctx.lineTo(9.6, 15.5);
  ctx.lineTo(17.2, 15.5);
  ctx.closePath();

  ctx.fillStyle = color;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "#09090b";
  ctx.stroke();

  if (label) {
    ctx.font = '700 12px "Inter", -apple-system, sans-serif';
    const tw = ctx.measureText(label).width;
    const px = 18, py = 20;
    roundRectPath(ctx, px, py, tw + 18, 24, 12);
    ctx.fillStyle = accent;
    ctx.fill();
    ctx.fillStyle = "#09090b";
    ctx.textBaseline = "middle";
    ctx.fillText(label, px + 9, py + 12.5);
  }
  ctx.restore();
}

export function drawKineticHeadline(ctx, text, x, y, t, {
  delay = 0,
  stagger = 0.055,
  font = '800 62px "Inter", "SF Pro Display", -apple-system, sans-serif',
  color = "#f4f4f5",
  accentWords = {},
  accentColor = "#f59e0b",
} = {}) {
  ctx.save();
  ctx.font = font;
  ctx.textBaseline = "alphabetic";
  const words = String(text).split(/\s+/);
  const spaceW = ctx.measureText(" ").width * 0.92;
  let curX = x;
  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    const p = springProgress(t, { delay: delay + i * stagger, damping: 16, stiffness: 210 });
    const alpha = clamp01(p * 1.25);
    const liftY = (1 - p) * 28;
    ctx.save();
    ctx.globalAlpha = alpha;
    const clean = word.replace(/[^a-zA-Z0-9/-]/g, "");
    ctx.fillStyle = accentWords[word] || accentWords[clean] ? accentColor : color;
    ctx.fillText(word, curX, y + liftY);
    ctx.restore();
    curX += ctx.measureText(word).width + spaceW;
  }
  ctx.restore();
}

export function drawBlurRevealText(ctx, text, x, y, progress, {
  font = '800 84px "Inter", "SF Pro Display", -apple-system, sans-serif',
  color = "#18181b",
  align = "center",
  baseline = "alphabetic",
  maxBlur = 16,
  liftPx = 18,
  alpha = 1,
} = {}) {
  const p = clamp01(progress);
  if (p <= 0.001) return;
  const sharp = easeOutCubic(p);
  const blurPx = Math.max(0, (1 - sharp) * maxBlur);
  ctx.save();
  ctx.font = font;
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  ctx.globalAlpha = clamp01(sharp * 1.15) * alpha;
  if ("filter" in ctx && blurPx > 0.25) {
    ctx.filter = `blur(${blurPx.toFixed(1)}px)`;
  }
  ctx.fillStyle = color;
  ctx.fillText(text, x, y + (1 - sharp) * liftPx);
  ctx.restore();
}

export function drawPearlCard(ctx, x, y, w, h, {
  radius = 28,
  bg = "rgba(255, 255, 255, 0.94)",
  border = "rgba(109, 93, 211, 0.14)",
  shadowColor = "rgba(65, 58, 128, 0.12)",
  shadowBlur = 34,
  activeBorder = null,
  activeGlow = null,
} = {}) {
  ctx.save();
  if (activeGlow) {
    ctx.shadowColor = activeGlow;
    ctx.shadowBlur = shadowBlur + 12;
    ctx.shadowOffsetY = 12;
  } else {
    ctx.shadowColor = shadowColor;
    ctx.shadowBlur = shadowBlur;
    ctx.shadowOffsetY = 14;
  }
  roundRectPath(ctx, x, y, w, h, radius);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
  ctx.lineWidth = activeBorder ? 2.2 : 1.25;
  ctx.strokeStyle = activeBorder || border;
  ctx.stroke();

  // Top translucent rim catch
  ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(x + radius, y + 1);
  ctx.lineTo(x + w - radius, y + 1);
  ctx.stroke();
  ctx.restore();
}

export function drawPortalFlash(ctx, W, H, progress, {
  cx = null,
  cy = null,
  color = "#f6f7fb",
  coreColor = "#ffffff",
  glowColor = "rgba(167, 139, 250, 0.55)",
} = {}) {
  const p = clamp01(progress);
  if (p <= 0.001) return;
  const ox = cx === null ? W * 0.5 : cx;
  const oy = cy === null ? H * 0.5 : cy;
  const maxR = Math.hypot(Math.max(ox, W - ox), Math.max(oy, H - oy)) * 1.18;
  const r = easeOutExpo(p) * maxR;
  ctx.save();
  const grad = ctx.createRadialGradient(ox, oy, Math.max(1, r * 0.15), ox, oy, Math.max(4, r));
  grad.addColorStop(0, coreColor);
  grad.addColorStop(0.55, color);
  grad.addColorStop(0.84, glowColor);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(ox, oy, r, 0, Math.PI * 2);
  ctx.fill();
  if (p > 0.65) {
    ctx.globalAlpha = smoothstep(0.65, 1.0, p);
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, W, H);
  }
  ctx.restore();
}

let _grainTileCanvas = null;
function _getGrainTile() {
  if (_grainTileCanvas) return _grainTileCanvas;
  const sz = 192;
  const c = document.createElement("canvas");
  c.width = sz;
  c.height = sz;
  const gctx = c.getContext("2d");
  const img = gctx.createImageData(sz, sz);
  const data = img.data;
  let seed = 0x9e3779b9;
  for (let i = 0; i < data.length; i += 4) {
    seed ^= seed << 13;
    seed ^= seed >>> 17;
    seed ^= seed << 5;
    const v = (seed & 0xff);
    data[i] = v;
    data[i + 1] = v;
    data[i + 2] = v;
    data[i + 3] = 255;
  }
  gctx.putImageData(img, 0, 0);
  _grainTileCanvas = c;
  return c;
}

export function drawFilmGrain(ctx, W, H, t, intensity = 0.038, {
  vignette = null,
  vignetteColor = null,
} = {}) {
  const tile = _getGrainTile();
  const frameIdx = Math.round(t * 60);
  const ox = (frameIdx * 53) % tile.width;
  const oy = (frameIdx * 89) % tile.height;

  ctx.save();
  // Diagonal-scaled optical prime-lens edge vignette (light-safe on luminous pearl backdrops)
  const vigAlpha = vignette !== null ? vignette : (intensity <= 0.028 ? 0.07 : 0.40);
  const vigRgb = vignetteColor !== null ? vignetteColor : (intensity <= 0.028 ? "135, 130, 185" : "0, 0, 0");
  if (vigAlpha > 0.001) {
    const diagR = Math.hypot(W, H) * 0.56;
    const innerR = diagR * 0.42;
    const vig = ctx.createRadialGradient(W * 0.5, H * 0.5, innerR, W * 0.5, H * 0.5, diagR);
    vig.addColorStop(0, `rgba(${vigRgb}, 0)`);
    vig.addColorStop(1, `rgba(${vigRgb}, ${vigAlpha})`);
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, W, H);
  }

  // 35mm organic monochrome film grain
  ctx.globalCompositeOperation = "overlay";
  ctx.globalAlpha = intensity;
  const pat = ctx.createPattern(tile, "repeat");
  if (pat) {
    ctx.translate(-ox, -oy);
    ctx.fillStyle = pat;
    ctx.fillRect(ox, oy, W + tile.width, H + tile.height);
  }
  ctx.restore();
}

// Legacy compatibility helpers preserved for external callers
export function drawStageBackdrop(ctx, W, H, t, opts = {}) {
  drawCraftBackdrop(ctx, W, H, t, { theme: "obsidian", ...opts });
}

export function drawDepthParticles(ctx, W, H, t, count = 24) {
  ctx.save();
  for (let i = 0; i < count; i++) {
    const seed = (i * 7919) % 997;
    const z = ((seed / 997) + t * 0.08) % 1;
    const angle = seed * 1.37;
    const radius = 180 + (seed % 720);
    const x = W * 0.5 + Math.cos(angle) * radius * (0.5 + z * 0.8);
    const y = H * 0.48 + Math.sin(angle * 0.9) * radius * 0.46 * (0.5 + z * 0.8);
    ctx.globalAlpha = Math.sin(z * Math.PI) * 0.28;
    ctx.fillStyle = i % 2 === 0 ? "#f59e0b" : "#e4e4e7";
    ctx.beginPath();
    ctx.arc(x, y, 1.0 + z * 2.0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

export function drawGlassCard(ctx, x, y, w, h, {
  radius = 14,
  fill = "rgba(20, 20, 24, 0.92)",
  border = "rgba(255, 255, 255, 0.10)",
  glow = null,
} = {}) {
  drawMachinedPanel(ctx, x, y, w, h, {
    radius,
    surfaceTop: fill,
    surfaceBot: fill,
    border,
    accentColor: glow,
  });
}

export function drawPill(ctx, x, y, text, {
  fg = "#f4f4f5",
  bg = "rgba(245, 158, 11, 0.14)",
  border = "rgba(245, 158, 11, 0.42)",
  font = '700 15px ui-monospace, "SFMono-Regular", Menlo, monospace',
  padX = 16,
  height = 34,
} = {}) {
  ctx.save();
  ctx.font = font;
  const tw = ctx.measureText(text).width;
  const w = tw + padX * 2;
  roundRectPath(ctx, x, y, w, height, height * 0.5);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = border;
  ctx.stroke();
  ctx.fillStyle = fg;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + padX, y + height * 0.5 + 0.5);
  ctx.restore();
  return w;
}

export function drawCornerHud(ctx, W, H, t, total, label = "KINEARC") {
  ctx.save();
  ctx.font = '600 13px ui-monospace, "SFMono-Regular", Menlo, monospace';
  ctx.fillStyle = "rgba(161, 161, 170, 0.55)";
  ctx.fillText(label, 64, 48);
  const tc = `${t.toFixed(2)}s`;
  const m = ctx.measureText(tc);
  ctx.fillText(tc, W - 64 - m.width, 48);
  ctx.restore();
}

export function registerScene({ width = 1920, height = 1080, fps = 60, totalDuration = 3.0, canvasId = "c", responsive = false, onFrame }) {
  const q = new URLSearchParams(location.search);
  const rawScale = parseFloat(q.get("scale") || "");
  const S = Number.isFinite(rawScale) && rawScale > 0 ? rawScale : 1;

  const logicalW = responsive && window.innerWidth > 0 ? Math.max(2, Math.round(window.innerWidth / S)) : width;
  const logicalH = responsive && window.innerHeight > 0 ? Math.max(2, Math.round(window.innerHeight / S)) : height;

  const canvas = document.getElementById(canvasId);
  canvas.width = Math.max(2, Math.round(logicalW * S));
  canvas.height = Math.max(2, Math.round(logicalH * S));
  canvas.style.width = "100vw";
  canvas.style.height = "100vh";
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");

  const gl = createWebGLRenderer(logicalW, logicalH, S);

  const seek = (rawTime) => {
    const t = clamp(Number.isFinite(rawTime) ? rawTime : 0, 0, totalDuration);
    ctx.setTransform(S, 0, 0, S, 0, 0);
    ctx.clearRect(0, 0, logicalW, logicalH);
    onFrame({ ctx, gl, W: logicalW, H: logicalH, scale: S, t, total: totalDuration, fps });
  };

  const rawT = parseFloat(q.get("t") || "");
  const initialT = Number.isFinite(rawT) && rawT > 0 ? rawT : 0;
  const fontsReady = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  const ready = fontsReady.then(() => seek(initialT));

  window.TOTAL = totalDuration;
  window.ready = ready;
  window.renderAt = seek;
  window.kinearc = { fps, totalDuration, ready, seek };
}

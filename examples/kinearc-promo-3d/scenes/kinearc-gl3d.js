/**
 * kinearc-gl3d.js — Zero-Dependency Deterministic WebGL2 3D + 2D HUD Runtime
 * Supports ?t=<sec>, ?scale=<S> (1080p -> 4K 3840x2160), window.kinearc,
 * procedural 3D PBR meshes (prism, torus, trefoil knot, slab, waveform bars),
 * perspective camera, spring easing, and editorial glassmorphic HUD helpers.
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
    // Upper bevel + spire
    pushTri(c0, c1, top1);
    pushTri(c0, top1, top0);
    pushTri(top0, top1, apex);
    // Lower bevel + nadir
    pushTri(c1, c0, bot0);
    pushTri(c1, bot0, bot1);
    pushTri(bot1, bot0, nadir);
  }
  return computeFlatNormalsMesh(pts);
}

export function createBoxMesh(w = 1, h = 1, d = 1) {
  const hw = w * 0.5, hh = h * 0.5, hd = d * 0.5;
  const faces = [
    [[hw, -hh, hd], [hw, hh, hd], [-hw, hh, hd], [-hw, -hh, hd]],     // +Z
    [[-hw, -hh, -hd], [-hw, hh, -hd], [hw, hh, -hd], [hw, -hh, -hd]], // -Z
    [[-hw, hh, hd], [hw, hh, hd], [hw, hh, -hd], [-hw, hh, -hd]],     // +Y
    [[-hw, -hh, -hd], [hw, -hh, -hd], [hw, -hh, hd], [-hw, -hh, hd]], // -Y
    [[hw, -hh, -hd], [hw, hh, -hd], [hw, hh, hd], [hw, -hh, hd]],     // +X
    [[-hw, -hh, hd], [-hw, hh, hd], [-hw, hh, -hd], [-hw, -hh, -hd]], // -X
  ];
  const pts = [];
  for (const [a, b, c, e] of faces) {
    pts.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]);
    pts.push(a[0], a[1], a[2], c[0], c[1], c[2], e[0], e[1], e[2]);
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
    const cu = Math.cos(u), su = Math.sin(u);
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
    const up = Math.abs(T[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
    let bx = T[1] * up[2] - T[2] * up[1];
    let by = T[2] * up[0] - T[0] * up[2];
    let bz = T[0] * up[1] - T[1] * up[0];
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

// ---------- WebGL2 PBR Renderer ----------
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
      vNrm = mat3(uModel) * aNrm;
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

      vec3 L1 = normalize(vec3(3.5, 4.5, 4.2));
      vec3 L2 = normalize(vec3(-4.0, -2.0, 2.5));
      vec3 H1 = normalize(L1 + V);
      vec3 H2 = normalize(L2 + V);

      float ndotl1 = max(dot(N, L1), 0.0);
      float ndotl2 = max(dot(N, L2), 0.0);
      float shininess = mix(128.0, 14.0, clamp(uRoughness, 0.05, 0.98));
      float spec1 = pow(max(dot(N, H1), 0.0), shininess);
      float spec2 = pow(max(dot(N, H2), 0.0), shininess * 0.65);

      float fresnel = pow(1.0 - max(dot(N, V), 0.0), 3.0);
      vec3 envTint = mix(vec3(0.06, 0.08, 0.16), vec3(0.32, 0.45, 0.78), N.y * 0.5 + 0.5);

      vec3 diff = uBaseColor * (0.14 + ndotl1 * 0.62 * uKeyColor + ndotl2 * 0.35 * uFillColor);
      vec3 specCol = mix(vec3(0.92), uBaseColor + vec3(0.25), uMetallic);
      vec3 spec = specCol * (spec1 * 0.95 * uKeyColor + spec2 * 0.45 * uFillColor);
      vec3 rim = mix(uKeyColor, uFillColor, 0.45) * fresnel * (0.45 + 0.45 * uMetallic);

      vec3 col = diff * (1.0 - 0.55 * uMetallic) + envTint * (0.15 + 0.35 * uMetallic) + spec + rim + uEmissive;
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
      fovDeg = 42,
      keyColor = [0.62, 0.78, 1.0],
      fillColor = [0.23, 0.85, 0.64],
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

      for (const obj of objects) {
        const rec = uploadMesh(obj.mesh);
        const model = mat4.transform(obj);
        const mvp = mat4.multiply(vp, model);
        gl.uniformMatrix4fv(uMVP, false, mvp);
        gl.uniformMatrix4fv(uModel, false, model);
        gl.uniform3fv(uBaseColor, obj.color || [0.42, 0.55, 1.0]);
        gl.uniform3fv(uEmissive, obj.emissive || [0, 0, 0]);
        gl.uniform1f(uRoughness, obj.roughness ?? 0.25);
        gl.uniform1f(uMetallic, obj.metallic ?? 0.72);
        gl.uniform1f(uAlpha, obj.alpha ?? 1.0);
        gl.bindVertexArray(rec.vao);
        gl.drawArrays(gl.TRIANGLES, 0, rec.count);
      }
      gl.bindVertexArray(null);
      gl.flush();
    },
  };
}

// ---------- 2D HUD & Stage Editorial Graphics Helpers ----------
export function drawStageBackdrop(ctx, W, H, t, { accentA = "#6c8cff", accentB = "#3ad29f", gridAlpha = 0.08 } = {}) {
  const bg = ctx.createRadialGradient(W * 0.5, H * 0.42, 60, W * 0.5, H * 0.5, W * 0.85);
  bg.addColorStop(0, "#11172a");
  bg.addColorStop(0.52, "#0b0e17");
  bg.addColorStop(1, "#06070c");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Perspective vanishing floor grid
  ctx.save();
  ctx.strokeStyle = `rgba(128, 154, 232, ${gridAlpha})`;
  ctx.lineWidth = 1.2;
  const horizonY = H * 0.58;
  const vpX = W * 0.5;
  for (let i = -10; i <= 10; i++) {
    ctx.beginPath();
    ctx.moveTo(vpX + i * 28, horizonY);
    ctx.lineTo(vpX + i * 240, H + 40);
    ctx.stroke();
  }
  for (let r = 0; r < 10; r++) {
    const frac = ((r + (t * 0.45) % 1) / 10);
    const y = horizonY + Math.pow(frac, 2.0) * (H - horizonY);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
  ctx.restore();

  // Ambient chromatic bloom blobs
  ctx.save();
  ctx.globalAlpha = 0.16;
  const g1 = ctx.createRadialGradient(W * 0.25, H * 0.28, 10, W * 0.25, H * 0.28, 460);
  g1.addColorStop(0, accentA);
  g1.addColorStop(1, "transparent");
  ctx.fillStyle = g1;
  ctx.fillRect(0, 0, W, H);

  const g2 = ctx.createRadialGradient(W * 0.78, H * 0.72, 10, W * 0.78, H * 0.72, 480);
  g2.addColorStop(0, accentB);
  g2.addColorStop(1, "transparent");
  ctx.fillStyle = g2;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

export function drawDepthParticles(ctx, W, H, t, count = 48) {
  ctx.save();
  for (let i = 0; i < count; i++) {
    const seed = (i * 7919) % 997;
    const z = ((seed / 997) + t * 0.14) % 1;
    const angle = seed * 1.37;
    const radius = 140 + (seed % 760);
    const x = W * 0.5 + Math.cos(angle) * radius * (0.45 + z * 0.9);
    const y = H * 0.48 + Math.sin(angle * 0.9) * radius * 0.48 * (0.45 + z * 0.9);
    const sz = 1.2 + z * 3.8;
    ctx.globalAlpha = Math.sin(z * Math.PI) * 0.65;
    ctx.fillStyle = i % 3 === 0 ? "#3ad29f" : (i % 3 === 1 ? "#6c8cff" : "#e2e8f0");
    ctx.beginPath();
    ctx.arc(x, y, sz, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

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

export function drawGlassCard(ctx, x, y, w, h, {
  radius = 16,
  fill = "rgba(15, 20, 34, 0.84)",
  border = "rgba(148, 175, 255, 0.24)",
  glow = null,
} = {}) {
  ctx.save();
  if (glow) {
    ctx.shadowColor = glow;
    ctx.shadowBlur = 28;
  } else {
    ctx.shadowColor = "rgba(0, 0, 0, 0.55)";
    ctx.shadowBlur = 24;
    ctx.shadowOffsetY = 12;
  }
  roundRectPath(ctx, x, y, w, h, radius);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = border;
  ctx.stroke();

  // Specular top bevel glint
  ctx.strokeStyle = "rgba(255, 255, 255, 0.14)";
  ctx.beginPath();
  ctx.moveTo(x + radius, y + 1);
  ctx.lineTo(x + w - radius, y + 1);
  ctx.stroke();
  ctx.restore();
}

export function drawPill(ctx, x, y, text, {
  fg = "#b7c8ff",
  bg = "rgba(108, 140, 255, 0.14)",
  border = "rgba(108, 140, 255, 0.42)",
  font = '700 18px ui-monospace, "SFMono-Regular", Menlo, monospace',
  padX = 18,
  height = 38,
} = {}) {
  ctx.save();
  ctx.font = font;
  const tw = ctx.measureText(text).width;
  const w = tw + padX * 2;
  roundRectPath(ctx, x, y, w, height, height * 0.5);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = border;
  ctx.stroke();
  ctx.fillStyle = fg;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + padX, y + height * 0.5 + 0.5);
  ctx.restore();
  return w;
}

export function drawCornerHud(ctx, W, H, t, total, label = "KINEARC V3.0") {
  ctx.save();
  const mono = '700 15px ui-monospace, "SFMono-Regular", Menlo, monospace';
  ctx.font = mono;
  ctx.fillStyle = "rgba(148, 163, 184, 0.72)";
  ctx.fillText(`${label}  ·  60.00 FPS  ·  ${W}×${H}`, 64, 54);
  const f = Math.min(Math.round(total * 60), Math.max(0, Math.round(t * 60)));
  const tc = `${t.toFixed(2)}s / ${total.toFixed(2)}s  ·  f${f}`;
  const m = ctx.measureText(tc);
  ctx.fillText(tc, W - 64 - m.width, 54);

  // Minimal hairline framing brackets
  ctx.strokeStyle = "rgba(108, 140, 255, 0.35)";
  ctx.lineWidth = 2;
  const b = 18;
  for (const [cx, cy, dx, dy] of [
    [40, 40, 1, 1],
    [W - 40, 40, -1, 1],
    [40, H - 40, 1, -1],
    [W - 40, H - 40, -1, -1],
  ]) {
    ctx.beginPath();
    ctx.moveTo(cx + dx * b, cy);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx, cy + dy * b);
    ctx.stroke();
  }
  ctx.restore();
}

export function registerScene({ width = 1920, height = 1080, fps = 60, totalDuration = 3.0, canvasId = "c", onFrame }) {
  const q = new URLSearchParams(location.search);
  const rawScale = parseFloat(q.get("scale") || "");
  const S = Number.isFinite(rawScale) && rawScale > 0 ? rawScale : 1;

  const canvas = document.getElementById(canvasId);
  canvas.width = Math.max(2, Math.round(width * S));
  canvas.height = Math.max(2, Math.round(height * S));
  canvas.style.width = "100vw";
  canvas.style.height = "100vh";
  canvas.style.display = "block";
  const ctx = canvas.getContext("2d");

  const gl = createWebGLRenderer(width, height, S);

  const seek = (rawTime) => {
    const t = clamp(Number.isFinite(rawTime) ? rawTime : 0, 0, totalDuration);
    ctx.setTransform(S, 0, 0, S, 0, 0);
    ctx.clearRect(0, 0, width, height);
    onFrame({ ctx, gl, W: width, H: height, scale: S, t, total: totalDuration, fps });
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

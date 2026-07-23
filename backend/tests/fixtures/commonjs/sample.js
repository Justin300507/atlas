const express = require("express");
const { Router } = require("./router");
require("./side-effect");

function build() {
  const nested = require("nested-package");
  return nested;
}

const dynamicPath = "./computed";
const dynamic = require(dynamicPath);

async function lazy() {
  const mod = await import("./lazy-module");
  return mod;
}

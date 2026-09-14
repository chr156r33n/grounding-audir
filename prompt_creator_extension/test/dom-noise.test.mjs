import assert from "node:assert/strict";
import test from "node:test";
import {
  NOISE_SELECTOR,
  classListLooksLikeNoise,
} from "../dom-noise.js";

test("does not treat article wrapper classes as noise", () => {
  assert.equal(
    classListLooksLikeNoise(
      "wp-singular no-sidebar wp-theme-four-seasons-magazine",
    ),
    false,
  );
  assert.equal(classListLooksLikeNoise("typography newsletter-post post"), false);
  assert.equal(classListLooksLikeNoise("post-header"), false);
  assert.equal(classListLooksLikeNoise("header-anchor-post"), false);
  assert.equal(classListLooksLikeNoise("has-sidebar"), false);
});

test("still treats real chrome classes as noise", () => {
  assert.equal(classListLooksLikeNoise("sidebar"), true);
  assert.equal(classListLooksLikeNoise("sidebar-widget"), true);
  assert.equal(classListLooksLikeNoise("site-header"), true);
  assert.equal(classListLooksLikeNoise("newsletter-signup"), true);
  assert.equal(classListLooksLikeNoise("socialShare"), true);
  assert.equal(classListLooksLikeNoise("nav-primary"), true);
});

test("noise selector avoids bare substring traps", () => {
  assert.doesNotMatch(NOISE_SELECTOR, /\[class\*="sidebar"/i);
  assert.doesNotMatch(NOISE_SELECTOR, /\[class\*="newsletter"/i);
  assert.doesNotMatch(NOISE_SELECTOR, /\[class\*="header"/i);
  assert.match(NOISE_SELECTOR, /\[class~="sidebar" i\]/);
  assert.match(NOISE_SELECTOR, /\[class~="newsletter" i\]/);
  assert.match(NOISE_SELECTOR, /\[class~="header" i\]/);
});

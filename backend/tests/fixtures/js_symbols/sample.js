import express from "express";

const router = express.Router();

router.get("/items", (req, res) => {
  res.json([]);
});

function helper() {
  return true;
}

class ItemService {
  get() {
    return null;
  }
}

export default router;

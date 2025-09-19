import React, { useState } from "react";
import axios from "axios";

function App() {
  const [ingredients, setIngredients] = useState("");
  const [recipes, setRecipes] = useState([]);

  const getRecipes = async () => {
    try {
      const response = await axios.post("http://127.0.0.1:8000/recommend", {
        ingredients: ingredients.split(","),
        k: 3
      });
      setRecipes(response.data.items);
    } catch (error) {
      console.error(error);
      alert("Error fetching recipes");
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>Recipe Recommender</h1>
      <input
        type="text"
        placeholder="Enter ingredients (comma separated)"
        value={ingredients}
        onChange={(e) => setIngredients(e.target.value)}
        style={{ width: "300px", marginRight: "10px" }}
      />
      <button onClick={getRecipes}>Get Recipes</button>

      <div style={{ marginTop: "20px" }}>
        {recipes.map((recipe, idx) => (
          <div
            key={idx}
            style={{ border: "1px solid gray", padding: "10px", marginBottom: "10px" }}
          >
            <h3>{recipe.title}</h3>
            <p><b>Ingredients:</b> {recipe.ingredients.join(", ")}</p>
            <p><b>Instructions:</b> {recipe.instructions}</p>
            <p><b>Matched:</b> {recipe.matched.join(", ")}</p>
            <p><b>Missing:</b> {recipe.missing.join(", ")}</p>
            <p><b>Score:</b> {recipe.score.toFixed(2)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;

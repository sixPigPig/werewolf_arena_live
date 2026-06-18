module.exports = {
  plugins: {
    "postcss-pxtorem": {
      rootValue: 37.5,
      propList: ["*"],
      minPixelValue: 2,
      selectorBlackList: ["html"],
      exclude: /node_modules/i,
    },
  },
};

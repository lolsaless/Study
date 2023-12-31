# Load package
library(networkD3)
df1 <- read_excel("sankey_data_6.xlsx", sheet = "시트1")
df2 <- read_excel("sankey_data_6.xlsx", sheet = "시트2")

df1 <- as.data.frame(df1)
df2 <- as.data.frame(df2)

sankeyNetwork(Links = df2, Nodes = df1, Source = "source",
              Target = "target", Value = "volume", NodeID = "name",
              units = "n", fontSize = 12, nodeWidth = 30)


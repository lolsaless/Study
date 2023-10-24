
# R Code for Plotting "Transformed Log Ca values by part" with different markers and density

## Importing Libraries
library(readxl)
library(ggplot2)
library(dplyr)
library(Metrics)

## Reading Data
df <- read_excel("ca_data_transformed.xlsx")

## Removing NaN rows
df <- df %>% drop_na(Transformed_Log_Ca)

## Adding density values
df$density <- density(df$Transformed_Log_Ca)$y

## Adding row numbers
df <- df %>% mutate(row_num = row_number())

## Plotting
ggplot(df, aes(x=row_num, y=Transformed_Log_Ca, color=as.factor(density), shape=part)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    labs(title="Transformed Log Ca Values by Part with Density", x="Index", y="Transformed_Log_Ca") +
    theme_minimal() +
    scale_colour_gradient(low="blue", high="yellow")

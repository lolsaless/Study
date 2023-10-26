# R Code for Data Transformation and Plotting

## Importing Libraries
library(readxl)
library(ggplot2)
library(car)
library(tidyverse)
library(ggrepel)

setwd("D:/github/R_coding/[사업] 2023_혼합음료/4. 양이온 표시기준 실제값 차이(Log변환)/Ca")

## Reading Data
df <- read_excel("ca_data.xlsx")

## Data Transformation
# Transforming Ca
df$Transformed_Ca <- df$Ca - df$Ca_max

# Log Transformation
df$Log_Ca_max <- log(df$Ca_max + 1)
df$Log_Ca <- log(df$Ca + 1)

# Log Transformed Ca
df$Transformed_Log_Ca <- df$Log_Ca - df$Log_Ca_max

## Adding row numbers
df <- df %>% mutate(row_num = row_number())

## Removing NaN rows
df <- df %>% drop_na(Transformed_Log_Ca)

## ChatGPT
dens_obj <- density(df$Transformed_Log_Ca)

# `Transformed_Log_Ca` 값을 기준으로 범주를 만드는 예시 코드
df$Level <- cut(df$Transformed_Log_Ca, 
                      breaks = c(-Inf, -1.5, -1, -0.5, 0.5, 1, Inf), 
                      labels = c("Very High", "High", "Medium", "Low", "Medium", "High"))

# ggplot 코드
ggplot(df, aes(x=row_num, y=Transformed_Log_Ca, color=Level, shape=Sample)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    geom_hline(yintercept=c(0.5, -0.5), linetype="dashed", color = "#4682B4") +
    labs(title="Transformed Log Ca Values", x="sample", y="Log Ca") +
    theme_minimal() +
    scale_colour_manual(values = c("Low" = "#2E8B57", "Medium" = "#FF8C00", "High" = "#D2691E", "Very High" = "#DC143C"))
